package com.jarvis.assistant;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.PowerManager;
import android.provider.Settings;

import androidx.activity.result.ActivityResult;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.BufferedReader;
import java.io.DataOutputStream;
import java.io.InputStreamReader;

/**
 * Real, native Android permission bridge for Jarvis.
 *
 * Every method here either (a) checks a genuine OS-level permission state,
 * or (b) opens the *real* system dialog for that permission (the same
 * Magisk root prompt / Android settings screen any other app would trigger)
 * — nothing here is simulated on the JS side.
 */
@CapacitorPlugin(
    name = "PermissionPlugin",
    permissions = {
        @Permission(strings = { Manifest.permission.RECORD_AUDIO }, alias = "microphone")
    }
)
public class PermissionPlugin extends Plugin {

    // ---------------------------------------------------------------
    // ROOT — invoking `su` is what makes Magisk show its real grant
    // dialog the first time this app asks. There is no other Android
    // API for "requesting" root; the su call itself IS the request.
    // ---------------------------------------------------------------

    @PluginMethod
    public void checkRoot(PluginCall call) {
        call.resolve(boolResult(isRootGranted()));
    }

    @PluginMethod
    public void requestRoot(PluginCall call) {
        // Same call as checkRoot: the OS/Magisk prompt appears the first
        // time `su` is invoked by this package, so "checking" root IS
        // the act of requesting it.
        call.resolve(boolResult(isRootGranted()));
    }

    private boolean isRootGranted() {
        Process process = null;
        try {
            process = Runtime.getRuntime().exec("su");
            DataOutputStream os = new DataOutputStream(process.getOutputStream());
            os.writeBytes("id\n");
            os.writeBytes("exit\n");
            os.flush();
            BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
            String line = reader.readLine();
            int exitCode = process.waitFor();
            return exitCode == 0 && line != null && line.contains("uid=0");
        } catch (Exception e) {
            return false;
        } finally {
            if (process != null) process.destroy();
        }
    }

    // ---------------------------------------------------------------
    // DISPLAY OVER OTHER APPS (overlay)
    // ---------------------------------------------------------------

    @PluginMethod
    public void checkOverlay(PluginCall call) {
        call.resolve(boolResult(Settings.canDrawOverlays(getContext())));
    }

    @PluginMethod
    public void requestOverlay(PluginCall call) {
        if (Settings.canDrawOverlays(getContext())) {
            call.resolve(boolResult(true));
            return;
        }
        saveCall(call);
        Intent intent = new Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            Uri.parse("package:" + getContext().getPackageName())
        );
        startActivityForResult(call, intent, "overlayResult");
    }

    @ActivityCallback
    private void overlayResult(PluginCall call, ActivityResult result) {
        if (call == null) return;
        call.resolve(boolResult(Settings.canDrawOverlays(getContext())));
    }

    // ---------------------------------------------------------------
    // ACCESSIBILITY SERVICE
    // ---------------------------------------------------------------

    @PluginMethod
    public void checkAccessibility(PluginCall call) {
        call.resolve(boolResult(isAccessibilityServiceEnabled()));
    }

    @PluginMethod
    public void requestAccessibility(PluginCall call) {
        if (isAccessibilityServiceEnabled()) {
            call.resolve(boolResult(true));
            return;
        }
        saveCall(call);
        Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
        startActivityForResult(call, intent, "accessibilityResult");
    }

    @ActivityCallback
    private void accessibilityResult(PluginCall call, ActivityResult result) {
        if (call == null) return;
        call.resolve(boolResult(isAccessibilityServiceEnabled()));
    }

    private boolean isAccessibilityServiceEnabled() {
        String target = getContext().getPackageName() + "/" + JarvisAccessibilityService.class.getCanonicalName();
        try {
            String enabled = Settings.Secure.getString(
                getContext().getContentResolver(),
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
            );
            return enabled != null && enabled.contains(target);
        } catch (Exception e) {
            return false;
        }
    }

    // ---------------------------------------------------------------
    // MICROPHONE — standard Android runtime permission (real system
    // dialog via Capacitor's permission machinery).
    // ---------------------------------------------------------------

    @PluginMethod
    public void checkMicrophone(PluginCall call) {
        call.resolve(boolResult(getPermissionState("microphone") == PermissionState.GRANTED));
    }

    @PluginMethod
    public void requestMicrophone(PluginCall call) {
        if (getPermissionState("microphone") == PermissionState.GRANTED) {
            call.resolve(boolResult(true));
            return;
        }
        requestPermissionForAlias("microphone", call, "microphoneCallback");
    }

    @PermissionCallback
    private void microphoneCallback(PluginCall call) {
        call.resolve(boolResult(getPermissionState("microphone") == PermissionState.GRANTED));
    }

    // ---------------------------------------------------------------
    // STORAGE (All-files access on Android 11+, matches this project's
    // target Android 11 device)
    // ---------------------------------------------------------------

    // Project targets Android 11+ only (minSdk 30), so this is always
    // the "all files access" flow — no legacy pre-R branch needed.

    @PluginMethod
    public void checkStorage(PluginCall call) {
        call.resolve(boolResult(Environment.isExternalStorageManager()));
    }

    @PluginMethod
    public void requestStorage(PluginCall call) {
        if (Environment.isExternalStorageManager()) {
            call.resolve(boolResult(true));
            return;
        }
        saveCall(call);
        Intent intent = new Intent(
            Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
            Uri.parse("package:" + getContext().getPackageName())
        );
        startActivityForResult(call, intent, "storageResult");
    }

    @ActivityCallback
    private void storageResult(PluginCall call, ActivityResult result) {
        if (call == null) return;
        call.resolve(boolResult(Environment.isExternalStorageManager()));
    }

    // ---------------------------------------------------------------
    // BATTERY OPTIMIZATION EXEMPTION
    // ---------------------------------------------------------------

    @PluginMethod
    public void checkBattery(PluginCall call) {
        call.resolve(boolResult(isIgnoringBatteryOptimizations()));
    }

    @PluginMethod
    public void requestBattery(PluginCall call) {
        if (isIgnoringBatteryOptimizations()) {
            call.resolve(boolResult(true));
            return;
        }
        saveCall(call);
        Intent intent = new Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
            Uri.parse("package:" + getContext().getPackageName())
        );
        startActivityForResult(call, intent, "batteryResult");
    }

    @ActivityCallback
    private void batteryResult(PluginCall call, ActivityResult result) {
        if (call == null) return;
        call.resolve(boolResult(isIgnoringBatteryOptimizations()));
    }

    private boolean isIgnoringBatteryOptimizations() {
        PowerManager pm = (PowerManager) getContext().getSystemService(Context.POWER_SERVICE);
        return pm != null && pm.isIgnoringBatteryOptimizations(getContext().getPackageName());
    }

    // ---------------------------------------------------------------

    private JSObject boolResult(boolean granted) {
        JSObject ret = new JSObject();
        ret.put("granted", granted);
        return ret;
    }
}
