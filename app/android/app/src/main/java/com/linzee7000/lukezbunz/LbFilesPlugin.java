package com.linzee7000.lukezbunz;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;

import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

/**
 * Saves a file the page made (the run map PDF) into the phone's Download folder, like a browser download, with a
 * "Downloaded" notification that opens it. The share sheet (Share plugin) never came up from the app, and the
 * Filesystem plugin's public folders didn't end up where Fox looked, so this does it the way Android wants:
 * MediaStore Downloads on Android 10 and later (no permission needed), the plain Download folder before that.
 * Called from the page through the bridge: Capacitor.nativePromise('LbFiles', 'saveDownload', { name, data, mime }).
 */
@CapacitorPlugin(name = "LbFiles")
public class LbFilesPlugin extends Plugin {
    static final String CHANNEL = "lb_downloads";

    @PluginMethod
    public void saveDownload(PluginCall call) {
        String name = call.getString("name", "run-map.pdf");
        String mime = call.getString("mime", "application/pdf");
        String data = call.getString("data");
        if (data == null || data.isEmpty()) { call.reject("nothing to save"); return; }
        byte[] bytes;
        try { bytes = Base64.decode(data, Base64.DEFAULT); } catch (Exception e) { call.reject("the file was damaged"); return; }
        Context ctx = getContext();
        Uri uri;
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentResolver cr = ctx.getContentResolver();
                ContentValues v = new ContentValues();
                v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                v.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
                v.put(MediaStore.MediaColumns.IS_PENDING, 1);
                uri = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) throw new Exception("Android would not make the file");
                OutputStream os = cr.openOutputStream(uri);
                if (os == null) throw new Exception("Android would not open the file");
                try { os.write(bytes); } finally { os.close(); }
                v.clear(); v.put(MediaStore.MediaColumns.IS_PENDING, 0);
                cr.update(uri, v, null, null);
            } else {
                File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
                if (!dir.exists()) dir.mkdirs();
                File f = new File(dir, name);
                FileOutputStream os = new FileOutputStream(f);
                try { os.write(bytes); } finally { os.close(); }
                uri = FileProvider.getUriForFile(ctx, ctx.getPackageName() + ".fileprovider", f);
            }
        } catch (Exception e) { call.reject("could not save: " + e.getMessage()); return; }
        boolean shown = false;
        try { shown = notifyDone(ctx, name, mime, uri); } catch (Exception ignored) {}
        JSObject r = new JSObject();
        r.put("uri", uri.toString());
        r.put("notified", shown);
        call.resolve(r);
    }

    // opens a saved file (the "Open" after a download)
    @PluginMethod
    public void open(PluginCall call) {
        String u = call.getString("uri"); String mime = call.getString("mime", "application/pdf");
        if (u == null) { call.reject("no file"); return; }
        try { getContext().startActivity(viewIntent(Uri.parse(u), mime)); call.resolve(); }
        catch (Exception e) { call.reject("no app on the phone opens this file: " + e.getMessage()); }
    }

    private Intent viewIntent(Uri uri, String mime) {
        Intent i = new Intent(Intent.ACTION_VIEW);
        i.setDataAndType(uri, mime);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        return i;
    }

    private boolean notifyDone(Context ctx, String name, String mime, Uri uri) {
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return false;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && nm.getNotificationChannel(CHANNEL) == null)
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Downloads", NotificationManager.IMPORTANCE_DEFAULT));
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0);
        int id = (int) (System.currentTimeMillis() & 0x7ffffff);
        PendingIntent pi = PendingIntent.getActivity(ctx, id, viewIntent(uri, mime), flags);
        Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O ? new Notification.Builder(ctx, CHANNEL) : new Notification.Builder(ctx);
        b.setSmallIcon(android.R.drawable.stat_sys_download_done)
         .setContentTitle("Downloaded")
         .setContentText(name)
         .setContentIntent(pi)
         .setAutoCancel(true);
        nm.notify(id, b.build());
        return true;
    }
}
