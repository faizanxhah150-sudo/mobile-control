package com.jarvis.assistant;

import android.accessibilityservice.AccessibilityService;
import android.view.accessibility.AccessibilityEvent;

/**
 * Registers Jarvis as a real, user-toggleable Accessibility Service.
 * This gives it a genuine entry in Settings > Accessibility (exactly
 * like TalkBack or any other accessibility tool) rather than a fake
 * in-app switch. Gesture/UI-reading logic will be layered on top of
 * this in a later step; for now it establishes the real permission.
 */
public class JarvisAccessibilityService extends AccessibilityService {

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // Intentionally minimal for this step — device UI automation is
        // handled primarily via uiautomator2 / root shell. This service
        // exists so the Accessibility permission is real, not simulated.
    }

    @Override
    public void onInterrupt() {
        // No-op.
    }
}
