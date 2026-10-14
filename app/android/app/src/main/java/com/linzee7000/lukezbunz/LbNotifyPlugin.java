package com.linzee7000.lukezbunz;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffColorFilter;
import android.graphics.RectF;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.View;
import android.widget.RemoteViews;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * The run-tracking notification: the run, its stream logo, the run time, the next break, and Start break / End break.
 * It replaces the plain "Tracking the run" notice the background GPS service shows (same notification id and channel),
 * so there is only ever one. The page sends the times (when the shift started, when the next break is due, when the
 * break began) and the phone rewrites the text itself every 15 s, so the times keep up even with the screen off and the
 * page asleep. On Android 7 and later the run time and the break are live timers (to the second, 7:11:22 - Fox is fine
 * with the colons for live seconds): a run-time count-up and a next-break count-down, which turns into "overdue by".
 */
@CapacitorPlugin(name = "LbNotify")
public class LbNotifyPlugin extends Plugin {
    static final String CHANNEL = "com.equimaps.capacitor_background_geolocation";   // the GPS service's own channel
    static final int ID = 28351;                                                    // ...and its notification id
    static final String ACTION = "com.linzee7000.lukezbunz.NOTIFY_ACTION";
    static LbNotifyPlugin instance;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean ticking = false;
    // what the page last sent
    private String run = "", stream = "", plainTitle = "Lukez Bunz", plainText = "Tracking the run";
    private long start = 0, breakAt = 0, breakStart = 0;
    private boolean onBreak = false, shift = false;
    private String lastKey = "";
    private Bitmap logo = null;
    private String logoFor = null;

    @Override
    public void load() { instance = this; }

    @PluginMethod
    public void update(PluginCall call) {
        run = call.getString("run", "");
        stream = call.getString("stream", "");
        plainTitle = call.getString("title", "Lukez Bunz");
        plainText = call.getString("text", "Tracking the run");
        shift = call.getBoolean("shift", false);
        onBreak = call.getBoolean("onBreak", false);
        start = num(call, "start");
        breakAt = num(call, "breakAt");
        breakStart = num(call, "breakStart");
        lastKey = "";
        try { post(); } catch (Exception e) { call.reject("notification failed: " + e.getMessage()); return; }
        if (!ticking) { ticking = true; handler.postDelayed(tick, 15000); }
        call.resolve();
    }

    private static long num(PluginCall call, String k) {
        Double d = call.getDouble(k);
        return d == null ? 0 : d.longValue();
    }

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            try { post(); } catch (Exception ignore) {}
            handler.postDelayed(this, 15000);
        }
    };

    private static String hm(long ms) {
        long m = Math.max(0, Math.abs(ms) / 60000);
        return String.format(java.util.Locale.ROOT, "%02d %02d", m / 60, m % 60);
    }

    private void post() {
        Context c = getContext();
        long now = System.currentTimeMillis();
        String title = plainTitle, text = plainText;
        if (shift && start > 0) {
            title = (run.isEmpty() ? "" : run + " · ") + "Run time " + hm(now - start);
            if (onBreak && breakStart > 0) text = "On break " + hm(now - breakStart);
            else if (breakAt > 0) text = breakAt <= now ? "Break overdue by " + hm(now - breakAt) : "Next break in " + hm(breakAt - now);
            else text = "";
        }
        boolean working = shift && start > 0;
        // (always our own body from Android 7: on shift two live timers, off shift a live clock)
        boolean live = Build.VERSION.SDK_INT >= Build.VERSION_CODES.N;
        String state = onBreak ? "break" : (breakAt > 0 && breakAt <= now ? "over" : (breakAt > 0 ? "due" : "none"));
        String key = live ? ("live|" + working + "|" + run + "|" + stream + "|" + start + "|" + state + "|" + breakAt + "|" + breakStart) : (title + "|" + text + "|" + stream + "|" + shift + "|" + run);
        if (key.equals(lastKey)) return;     // nothing has changed since the last write
        lastKey = key;

        Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
        b.setContentTitle(title).setContentText(text).setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false);
        int icon = c.getResources().getIdentifier("ic_stat_lb", "drawable", c.getPackageName());
        if (icon == 0) icon = c.getResources().getIdentifier("ic_launcher", "mipmap", c.getPackageName());
        b.setSmallIcon(icon != 0 ? icon : android.R.drawable.ic_menu_mylocation);
        Bitmap lg = streamLogo(c);
        if (live) {
            // our own body with two live timers; Android keeps drawing the header and the buttons round it
            RemoteViews rv = new RemoteViews(c.getPackageName(), R.layout.lb_notify);
            long el = SystemClock.elapsedRealtime();
            if (!working) {
                // not on a shift: the run, and the time of day ticking along live
                rv.setTextViewText(R.id.lb_t1, (run.isEmpty() ? "" : run + " · ") + plainText);
                rv.setViewVisibility(R.id.lb_c1, View.GONE);
                rv.setTextViewText(R.id.lb_t2, "");
                rv.setViewVisibility(R.id.lb_c2, View.GONE);
                rv.setViewVisibility(R.id.lb_clk, View.VISIBLE);
            } else {
            rv.setTextViewText(R.id.lb_t1, (run.isEmpty() ? "" : run + " · ") + "Run time ");
            rv.setChronometer(R.id.lb_c1, el - (now - start), null, true);
            if (state.equals("break")) {
                rv.setTextViewText(R.id.lb_t2, "On break ");
                rv.setChronometer(R.id.lb_c2, el - (now - breakStart), null, true);
                rv.setChronometerCountDown(R.id.lb_c2, false);
            } else if (state.equals("due")) {
                rv.setTextViewText(R.id.lb_t2, "Next break in ");
                rv.setChronometer(R.id.lb_c2, el + (breakAt - now), null, true);
                rv.setChronometerCountDown(R.id.lb_c2, true);
            } else if (state.equals("over")) {
                rv.setTextViewText(R.id.lb_t2, "Break overdue by ");
                rv.setChronometer(R.id.lb_c2, el - (now - breakAt), null, true);
                rv.setChronometerCountDown(R.id.lb_c2, false);
            } else {
                rv.setTextViewText(R.id.lb_t2, "");
                rv.setViewVisibility(R.id.lb_c2, View.GONE);
            }
            }
            if (lg != null) rv.setImageViewBitmap(R.id.lb_logo, lg); else rv.setViewVisibility(R.id.lb_logo, View.GONE);
            b.setCustomContentView(rv);
            b.setStyle(new Notification.DecoratedCustomViewStyle());
        } else if (lg != null) b.setLargeIcon(lg);
        Intent open = c.getPackageManager().getLaunchIntentForPackage(c.getPackageName());
        if (open != null) {
            open.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
            b.setContentIntent(PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        }
        if (shift) {
            b.addAction(action(c, "breakStart", "Start break", 1));
            b.addAction(action(c, "breakEnd", "End break", 2));
        }
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(ID, b.build());
    }

    // the run's stream as the app's run chips show it: its logo in a box of the stream's colour
    private Bitmap streamLogo(Context c) {
        if (stream == null || stream.isEmpty()) return null;
        String lk = stream + "|" + run;
        if (lk.equals(logoFor)) return logo;
        String res; int bg; boolean white;
        switch (stream) {
            case "garbage": res = "lb_garbage"; bg = Color.parseColor("#ff4d3d"); white = true; break;
            case "recycle": res = "lb_recycle"; bg = Color.parseColor("#ffd21f"); white = false; break;
            case "fogo":    res = "lb_fogo";    bg = Color.parseColor("#2fd16a"); white = false; break;
            case "litter":  res = "lb_litter";  bg = Color.parseColor("#3b82f6"); white = true; break;
            default: return null;
        }
        int id = c.getResources().getIdentifier(res, "drawable", c.getPackageName());
        if (id == 0) return null;
        Bitmap src = BitmapFactory.decodeResource(c.getResources(), id);
        if (src == null) return null;
        int n = 192;
        Bitmap out = Bitmap.createBitmap(n, n, Bitmap.Config.ARGB_8888);
        Canvas cv = new Canvas(out);
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setColor(bg);
        cv.drawRoundRect(new RectF(0, 0, n, n), n * 0.18f, n * 0.18f, p);
        Paint lp = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
        lp.setColorFilter(new PorterDuffColorFilter(white ? Color.WHITE : Color.BLACK, PorterDuff.Mode.SRC_IN));
        float sc = Math.min(n * 0.62f / src.getWidth(), n * 0.62f / src.getHeight());
        float w = src.getWidth() * sc, h = src.getHeight() * sc;
        String label = run == null ? "" : run.replaceAll("\\s+", "").toUpperCase(java.util.Locale.ROOT);
        if (!label.isEmpty()) {
            // the whole run number (227B) in the stream's colour box, in place of the logo
            Paint tp = new Paint(Paint.ANTI_ALIAS_FLAG);
            tp.setColor(white ? Color.WHITE : Color.BLACK);
            tp.setTypeface(android.graphics.Typeface.create(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD));
            tp.setTextAlign(Paint.Align.CENTER);
            float ts = n * 0.62f;
            tp.setTextSize(ts);
            float tw = tp.measureText(label);
            if (tw > n * 0.88f) { ts = ts * n * 0.88f / tw; tp.setTextSize(ts); }
            cv.drawRoundRect(new RectF(0, 0, n, n), n * 0.18f, n * 0.18f, p);
            Paint.FontMetrics fm = tp.getFontMetrics();
            cv.drawText(label, n / 2f, n / 2f - (fm.ascent + fm.descent) / 2f, tp);
        } else
        cv.drawBitmap(src, null, new RectF((n - w) / 2, (n - h) / 2, (n + w) / 2, (n + h) / 2), lp);
        logo = out; logoFor = lk;
        return out;
    }

    private Notification.Action action(Context c, String what, String label, int req) {
        Intent i = new Intent(c, Receiver.class).setAction(ACTION).putExtra("a", what);
        PendingIntent pi = PendingIntent.getBroadcast(c, req, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Action.Builder(null, label, pi).build();
    }

    void fire(String what) {
        // show the change straight away (the page confirms with the real times a moment later)
        if ("breakStart".equals(what) && shift && !onBreak) { onBreak = true; breakStart = System.currentTimeMillis(); lastKey = ""; try { post(); } catch (Exception ignore) {} }
        if ("breakEnd".equals(what) && onBreak) { onBreak = false; lastKey = ""; try { post(); } catch (Exception ignore) {} }
        JSObject d = new JSObject();
        d.put("a", what);
        notifyListeners("action", d, true);
    }

    public static class Receiver extends BroadcastReceiver {
        @Override
        public void onReceive(Context context, Intent intent) {
            String a = intent.getStringExtra("a");
            if (a != null && instance != null) instance.fire(a);
        }
    }
}
