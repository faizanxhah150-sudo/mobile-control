package com.jarvis.assistant;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.util.Log;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.Locale;

/**
 * Runs a continuous, silent (no popup, no dialog) speech-recognition loop in
 * the background so the user can just say the agent's name — whatever they
 * set it to, e.g. "Jarvis", "Nexus", "Hal" — followed by a command, without
 * having the app open.
 *
 * Android requires a foreground service (with a visible-but-minimal
 * notification) for any background microphone use — that notification is
 * the OS's own security requirement, not a popup we chose to show. We keep
 * it as quiet/low-priority as Android allows: no sound, no heads-up alert,
 * just a small persistent icon while it's running.
 *
 * Recognized speech is only forwarded to the backend if it contains the
 * wake word, so idle background conversation doesn't trigger commands.
 * The backend (jarvis_engine.py) speaks the reply itself via edge-tts, so
 * this service doesn't do any of its own text-to-speech.
 */
public class BackgroundListenerService extends Service implements RecognitionListener {

    private static final String TAG = "JarvisBgListener";
    private static final String CHANNEL_ID = "jarvis_bg_listener";
    private static final int NOTIF_ID = 4242;

    private SpeechRecognizer recognizer;
    private Handler handler;
    private String agentName = "Jarvis";
    private String endpoint = "http://127.0.0.1:5000";
    private boolean running = false;

    @Override
    public void onCreate() {
        super.onCreate();
        handler = new Handler(Looper.getMainLooper());
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) {
            if (intent.hasExtra("agentName")) agentName = intent.getStringExtra("agentName");
            if (intent.hasExtra("endpoint")) endpoint = intent.getStringExtra("endpoint");
        }
        startForeground(NOTIF_ID, buildNotification());
        running = true;
        startListeningLoop();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        if (recognizer != null) {
            try {
                recognizer.stopListening();
                recognizer.destroy();
            } catch (Exception ignored) { }
        }
        super.onDestroy();
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // --- Notification (minimal, silent, no popup) ---

    private Notification buildNotification() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "Jarvis background listening",
                    NotificationManager.IMPORTANCE_MIN);
            channel.setShowBadge(false);
            channel.setSound(null, null);
            nm.createNotificationChannel(channel);
        }
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle(agentName + " is listening")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setPriority(NotificationCompat.PRIORITY_MIN)
                .setOngoing(true)
                .setSilent(true)
                .build();
    }

    // --- Listening loop ---

    private void startListeningLoop() {
        handler.post(() -> {
            if (!running) return;
            if (recognizer == null) {
                recognizer = SpeechRecognizer.createSpeechRecognizer(this);
                recognizer.setRecognitionListener(this);
            }
            Intent recognizerIntent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            recognizerIntent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                    RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            recognizerIntent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault());
            recognizerIntent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
            recognizerIntent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1200);
            try {
                recognizer.startListening(recognizerIntent);
            } catch (Exception e) {
                Log.w(TAG, "startListening failed, retrying shortly", e);
                restartSoon(1500);
            }
        });
    }

    // Restart the loop after a short pause — used after errors/results so we
    // don't hammer the recognizer in a tight loop, and so there's no gap
    // that feels laggy to the user ("bagair delay ke").
    private void restartSoon(long delayMs) {
        handler.postDelayed(this::startListeningLoop, delayMs);
    }

    // --- RecognitionListener callbacks ---

    @Override
    public void onResults(Bundle results) {
        ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        if (matches != null && !matches.isEmpty()) {
            String heard = matches.get(0);
            handleHeardText(heard);
        }
        restartSoon(150);
    }

    @Override
    public void onError(int error) {
        // ERROR_NO_MATCH / ERROR_SPEECH_TIMEOUT happen constantly during
        // silence — that's normal, just listen again immediately.
        restartSoon(300);
    }

    @Override public void onReadyForSpeech(Bundle params) { }
    @Override public void onBeginningOfSpeech() { }
    @Override public void onRmsChanged(float rmsdB) { }
    @Override public void onBufferReceived(byte[] buffer) { }
    @Override public void onEndOfSpeech() { }
    @Override public void onPartialResults(Bundle partialResults) { }
    @Override public void onEvent(int eventType, Bundle params) { }

    // --- Wake-word check + forward to backend ---

    private void handleHeardText(String heard) {
        if (heard == null || heard.trim().isEmpty()) return;
        String lowerHeard = heard.toLowerCase(Locale.getDefault());
        String lowerName = agentName == null ? "jarvis" : agentName.toLowerCase(Locale.getDefault());
        if (!lowerHeard.contains(lowerName)) {
            // Wake word not present — ignore, keep listening silently.
            return;
        }
        Log.i(TAG, "Wake word matched, forwarding: " + heard);
        // Network call off the main thread.
        new Thread(() -> sendToBackend(heard)).start();
    }

    private void sendToBackend(String prompt) {
        try {
            URL url = new URL(endpoint.replaceAll("/$", "") + "/process");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(60000);

            JSONObject body = new JSONObject();
            body.put("prompt", prompt);
            body.put("agent_name", agentName);
            body.put("mode", "responsive");

            try (OutputStream os = conn.getOutputStream()) {
                os.write(body.toString().getBytes("UTF-8"));
            }
            // We don't need to read/parse the reply here — the backend
            // already speaks it aloud via edge-tts on the Termux side.
            conn.getResponseCode();
            conn.disconnect();
        } catch (Exception e) {
            Log.w(TAG, "Failed to reach backend: " + e.getMessage());
        }
    }
}
