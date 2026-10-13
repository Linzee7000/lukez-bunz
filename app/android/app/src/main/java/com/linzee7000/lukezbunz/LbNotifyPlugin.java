package com.linzee7000.lukezbunz;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * The run-tracking notification with the run time, the next break and Start break / End break buttons.
 * It replaces the plain "Tracking the run" notice that the background GPS service shows (same notification id and
 * channel), so there is still only one notification. The page sends the text every so often (LbNotify.update);
 * the buttons come back to the page as an "action" event without opening the app.
 */
@CapacitorPlugin(name = "LbNotify")
public class LbNotifyPlugin extends Plugin {
    static final String CHANNEL = "com.equimaps.capacitor_background_geolocation";   // the GPS service's own channel
    static final int ID = 28351;                                                    // ...and its notification id
    static final String ACTION = "com.linzee7000.lukezbunz.NOTIFY_ACTION";
    static LbNotifyPlugin instance;

    @Override
    public void load() { instance = this; }

    @PluginMethod
    public void update(PluginCall call) {
        try {
            Context c = getContext();
            Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
            b.setContentTitle(call.getString("title", "Lukez Bunz"))
             .setContentText(call.getString("text", "Tracking the run"))
             .setOngoing(true)
             .setOnlyAlertOnce(true)
             .setShowWhen(false);
            int icon = c.getResources().getIdentifier("ic_launcher", "mipmap", c.getPackageName());
            b.setSmallIcon(icon != 0 ? icon : android.R.drawable.ic_menu_mylocation);
            Intent open = c.getPackageManager().getLaunchIntentForPackage(c.getPackageName());
            if (open != null) {
                open.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
                b.setContentIntent(PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
            }
            if (call.getBoolean("buttons", false)) {
                b.addAction(action(c, "breakStart", "Start break", 1));
                b.addAction(action(c, "breakEnd", "End break", 2));
            }
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) nm.notify(ID, b.build());
            call.resolve();
        } catch (Exception e) {
            call.reject("notification failed: " + e.getMessage());
        }
    }

    private Notification.Action action(Context c, String what, String label, int req) {
        Intent i = new Intent(c, Receiver.class).setAction(ACTION).putExtra("a", what);
        PendingIntent pi = PendingIntent.getBroadcast(c, req, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Action.Builder(null, label, pi).build();
    }

    void fire(String what) {
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
