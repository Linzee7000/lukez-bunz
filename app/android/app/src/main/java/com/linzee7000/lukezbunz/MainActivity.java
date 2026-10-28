package com.linzee7000.lukezbunz;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebView;

import com.getcapacitor.BridgeActivity;
import com.getcapacitor.WebViewListener;

public class MainActivity extends BridgeActivity {

    // Battery optimisation stops the GPS in the background (on Samsung it is the "Optimised" battery setting;
    // allowing this makes it "Unrestricted"). Android does not let an app switch it off by itself, so every time
    // the app comes to the front without the exemption it asks again with the system's own Allow / Deny box.
    // On the managed tablets Scalefusion can grant the exemption, and then this never shows.
    private long lastAsked = 0;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(LbNotifyPlugin.class);   // the run notification with the break buttons
        registerPlugin(LbFilesPlugin.class);    // saving the run map PDF to Downloads, with a Downloaded notification
        super.onCreate(savedInstanceState);
        keepPageAlive();
    }

    // (Fox, 28 Oct: "not sending the updates in the background, it says offline xxx minutes" and "occasionally when you go
    // back into the app the screen is black and nothing happens".) The page runs in Chrome's own "renderer" process. With
    // the app in the background Android treats that process as unimportant: it gets little CPU, so the page's work (the
    // 2-minute progress for Live runs) hardly runs, and when memory is short Android kills it. A killed renderer leaves the
    // app black - Capacitor does nothing about it. So: keep the renderer as important as the app itself (the background
    // GPS service keeps the app important), reload the page if it is killed anyway, and reload it if it does not answer
    // within 10 s of coming back to the front.
    private final Handler main = new Handler(Looper.getMainLooper());
    private long pageLoadedAt = 0;
    private volatile long lastPong = 0;

    private void keepPageAlive() {
        if (bridge == null) return;
        final WebView wv = bridge.getWebView();
        if (wv != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            try { wv.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false); } catch (Exception ignored) {}
        }
        bridge.addWebViewListener(new WebViewListener() {
            @Override public void onPageLoaded(WebView webView) { pageLoadedAt = System.currentTimeMillis(); }
            @Override public boolean onRenderProcessGone(WebView webView, RenderProcessGoneDetail detail) {
                // the WebView can't be used again once its renderer is gone: start the screen afresh (the run, trail and
                // reports are saved on the phone, so nothing is lost)
                main.post(MainActivity.this::recreate);
                return true;
            }
        });
    }

    private void checkPageAnswers() {
        if (bridge == null || bridge.getWebView() == null) return;
        if (pageLoadedAt == 0 || System.currentTimeMillis() - pageLoadedAt < 30_000) return;   // still starting up
        final long asked = System.currentTimeMillis();
        try { bridge.getWebView().evaluateJavascript("1", v -> lastPong = System.currentTimeMillis()); } catch (Exception e) { return; }
        main.postDelayed(() -> {
            if (lastPong >= asked || isFinishing()) return;
            try { pageLoadedAt = 0; bridge.getWebView().reload(); } catch (Exception e) { recreate(); }
        }, 10_000);
    }

    @Override
    public void onResume() {
        super.onResume();
        checkPageAnswers();
        askToIgnoreBatteryOptimisation();
    }

    @SuppressLint("BatteryLife")
    private void askToIgnoreBatteryOptimisation() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return;
        try {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm == null || pm.isIgnoringBatteryOptimizations(getPackageName())) return;
            long now = System.currentTimeMillis();
            if (now - lastAsked < 60_000) return;          // the box itself pauses and resumes the app: don't loop
            lastAsked = now;
            Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
            i.setData(Uri.parse("package:" + getPackageName()));
            startActivity(i);
        } catch (Exception e) {
            // some phones block the direct box: open the battery optimisation list instead
            try { startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)); } catch (Exception ignored) {}
        }
    }
}
