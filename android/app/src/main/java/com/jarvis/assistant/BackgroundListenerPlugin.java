package com.jarvis.assistant;

import android.content.Intent;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "BackgroundListenerPlugin")
public class BackgroundListenerPlugin extends Plugin {

    @PluginMethod
    public void start(PluginCall call) {
        String agentName = call.getString("agentName", "Jarvis");
        String endpoint = call.getString("endpoint", "http://127.0.0.1:5000");

        Intent intent = new Intent(getContext(), BackgroundListenerService.class);
        intent.putExtra("agentName", agentName);
        intent.putExtra("endpoint", endpoint);
        getContext().startForegroundService(intent);

        JSObject ret = new JSObject();
        ret.put("started", true);
        call.resolve(ret);
    }

    @PluginMethod
    public void stop(PluginCall call) {
        Intent intent = new Intent(getContext(), BackgroundListenerService.class);
        getContext().stopService(intent);

        JSObject ret = new JSObject();
        ret.put("stopped", true);
        call.resolve(ret);
    }
}
