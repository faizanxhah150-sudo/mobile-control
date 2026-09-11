package com.jarvis.assistant;

import android.content.Intent;
import android.os.Build;
import android.provider.Settings;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "OverlayPlugin")
public class OverlayPlugin extends Plugin {

    @PluginMethod
    public void start(PluginCall call) {
        if (!Settings.canDrawOverlays(getContext())) {
            call.reject("Overlay permission not granted");
            return;
        }

        String avatarBase64 = call.getString("avatar", "");
        int sizeDp = call.getInt("size", 80);

        Intent intent = new Intent(getContext(), OverlayService.class);
        intent.setAction(OverlayService.ACTION_START);
        intent.putExtra(OverlayService.EXTRA_AVATAR_BASE64, avatarBase64);
        intent.putExtra(OverlayService.EXTRA_SIZE_DP, sizeDp);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getContext().startForegroundService(intent);
        } else {
            getContext().startService(intent);
        }

        JSObject ret = new JSObject();
        ret.put("started", true);
        call.resolve(ret);
    }

    @PluginMethod
    public void stop(PluginCall call) {
        Intent intent = new Intent(getContext(), OverlayService.class);
        intent.setAction(OverlayService.ACTION_STOP);
        getContext().startService(intent);

        JSObject ret = new JSObject();
        ret.put("stopped", true);
        call.resolve(ret);
    }
}
