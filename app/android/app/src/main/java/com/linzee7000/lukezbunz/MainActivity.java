package com.linzee7000.lukezbunz;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;

import com.getcapacitor.BridgeActivity;

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
    }

    @Override
    public void onResume() {
        super.onResume();
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
