package com.jarvis.assistant;

import android.animation.ValueAnimator;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.PixelFormat;
import android.os.Build;
import android.os.IBinder;
import android.util.Base64;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.animation.LinearInterpolator;
import android.widget.ImageView;

import androidx.annotation.Nullable;

/**
 * A REAL system-wide floating overlay — a WindowManager view drawn above
 * every other app, exactly like Messenger's chat heads. This is not an
 * in-page HTML element; it keeps showing even after the Jarvis app itself
 * is closed/swiped away, because it lives inside this foreground service.
 *
 * Only starts if the user picked an avatar and pressed Start — if no
 * avatar is selected, JS simply never calls start(), so nothing appears
 * on screen; only the (minimum-priority, silent) foreground-service
 * notification shows, as required.
 */
public class OverlayService extends Service {

    public static final String ACTION_START = "com.jarvis.assistant.action.START_OVERLAY";
    public static final String ACTION_STOP = "com.jarvis.assistant.action.STOP_OVERLAY";
    public static final String EXTRA_AVATAR_BASE64 = "avatar_base64";
    public static final String EXTRA_SIZE_DP = "size_dp";

    private static final String CHANNEL_ID = "jarvis_overlay_channel";
    private static final int NOTIFICATION_ID = 4201;

    private WindowManager windowManager;
    private ImageView overlayView;
    private WindowManager.LayoutParams params;
    private ValueAnimator idleAnimator;

    @Override
    public void onCreate() {
        super.onCreate();
        windowManager = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) return START_STICKY;

        if (ACTION_STOP.equals(intent.getAction())) {
            removeOverlay();
            stopForeground(true);
            stopSelf();
            return START_NOT_STICKY;
        }

        startForeground(NOTIFICATION_ID, buildNotification());

        String avatarBase64 = intent.getStringExtra(EXTRA_AVATAR_BASE64);
        int sizeDp = intent.getIntExtra(EXTRA_SIZE_DP, 80);
        showOverlay(avatarBase64, sizeDp);
        return START_STICKY;
    }

    private Notification buildNotification() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Jarvis", NotificationManager.IMPORTANCE_MIN
            );
            channel.setShowBadge(false);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(channel);
        }
        return new Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Jarvis is running")
            .setContentText("Tap to open")
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setOngoing(true)
            .setPriority(Notification.PRIORITY_MIN)
            .build();
    }

    private void showOverlay(@Nullable String avatarBase64, int sizeDp) {
        if (overlayView != null) return; // already showing, avoid duplicate view

        overlayView = new ImageView(this);
        if (avatarBase64 != null && !avatarBase64.isEmpty()) {
            try {
                String pure = avatarBase64.contains(",")
                    ? avatarBase64.substring(avatarBase64.indexOf(',') + 1)
                    : avatarBase64;
                byte[] bytes = Base64.decode(pure, Base64.DEFAULT);
                Bitmap bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
                overlayView.setImageBitmap(bmp);
            } catch (Exception ignored) {
                // fall through with an empty ImageView rather than crash
            }
        }

        int sizePx = (int) (sizeDp * getResources().getDisplayMetrics().density);
        int layoutType = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            : WindowManager.LayoutParams.TYPE_PHONE;

        params = new WindowManager.LayoutParams(
            sizePx,
            sizePx,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        );
        params.gravity = Gravity.TOP | Gravity.START;
        params.x = 20;
        params.y = 300;

        windowManager.addView(overlayView, params);
        attachDragToMove();
        startIdleSwayAnimation();
    }

    private void attachDragToMove() {
        overlayView.setOnTouchListener(new View.OnTouchListener() {
            private int initialX, initialY;
            private float initialTouchX, initialTouchY;

            @Override
            public boolean onTouch(View v, MotionEvent event) {
                switch (event.getAction()) {
                    case MotionEvent.ACTION_DOWN:
                        initialX = params.x;
                        initialY = params.y;
                        initialTouchX = event.getRawX();
                        initialTouchY = event.getRawY();
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        params.x = initialX + (int) (event.getRawX() - initialTouchX);
                        params.y = initialY + (int) (event.getRawY() - initialTouchY);
                        windowManager.updateViewLayout(overlayView, params);
                        return true;
                    default:
                        return false;
                }
            }
        });
    }

    /** Subtle idle bob + sway only — deliberately NOT a mouth/lip animation. */
    private void startIdleSwayAnimation() {
        idleAnimator = ValueAnimator.ofFloat(0f, 1f);
        idleAnimator.setDuration(2400);
        idleAnimator.setRepeatMode(ValueAnimator.RESTART);
        idleAnimator.setRepeatCount(ValueAnimator.INFINITE);
        idleAnimator.setInterpolator(new LinearInterpolator());
        idleAnimator.addUpdateListener(anim -> {
            if (overlayView == null) return;
            float t = (float) anim.getAnimatedValue();
            double angle = t * Math.PI * 2;
            overlayView.setTranslationY((float) (Math.sin(angle) * 4));
            overlayView.setRotation((float) (Math.sin(angle) * 2));
        });
        idleAnimator.start();
    }

    private void removeOverlay() {
        if (idleAnimator != null) {
            idleAnimator.cancel();
            idleAnimator = null;
        }
        if (overlayView != null && windowManager != null) {
            windowManager.removeView(overlayView);
            overlayView = null;
        }
    }

    @Override
    public void onDestroy() {
        removeOverlay();
        super.onDestroy();
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
