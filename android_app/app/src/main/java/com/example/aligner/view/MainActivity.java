package com.example.aligner.view;

import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.os.Bundle;

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.Toolbar;

import android.preference.PreferenceManager;
import android.util.Log;
import android.view.KeyEvent;
import android.view.View;
import android.widget.TextView;

import android.view.Menu;
import android.view.MenuItem;
import android.widget.CompoundButton;
import android.widget.Switch;

import com.example.aligner.R;
import com.example.aligner.controller.JSONListener;
import com.example.aligner.controller.NetworkingController;
import com.example.aligner.model.Constants;

import org.json.JSONObject;

/**
 * @details Requirements
 * An app that connects to a web page and scrapes numbers from it. One number is selected and it's
 * value determines the tone of a sine wave played to the user. Then as the value changes (E.G
 * antenna alignment is changed) the tone is changed. The tone increases in frequency as the
 * signal level increases. This allows a user to align an antenna to get maximum signal.
 *
 * Use Case (requires that xsender app is running on a machine in the network)
 *
 * Start Aligner
 * - Send UDP broadcast message to local subnet for 10 seconds every 0.5 seconds)
 * - Listen for responses
 *   - If multiple responses then ask user to select the xsender source.
 * - Build socket connection to port 50265
 * - Send hello json message and wait for OK json response
 * - wait for value, min and max json message
 * - Generate a tone based upon the value received and it's relative distance from min and max.
 */
public class MainActivity extends AppCompatActivity implements JSONListener, CompoundButton.OnCheckedChangeListener {
    int freqHz;
    AudioTrack audioTrack;
    SharedPreferences sharedPreferences;
    NetworkingController networkingController;
    int lastRXP=-1000;
    Switch toneSwitch;
    TextView rxpTextView;
    int initialRXP = -1000;
    boolean active = false;

    /**
     * @brief Constructor
     * @param savedInstanceState
     */
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        Toolbar toolbar = findViewById(R.id.toolbar);
        setSupportActionBar(toolbar);

        sharedPreferences = PreferenceManager.getDefaultSharedPreferences(this.getBaseContext());
        freqHz = getDefaultToneHz();
        toneSwitch = (Switch)  findViewById(R.id.toneSwitch);
        rxpTextView = (TextView)  findViewById(R.id.rxpTextView);
        toneSwitch.setChecked( getToneOnAtStartup() );
        toneSwitch.setOnCheckedChangeListener(this);
        active = toneSwitch.isChecked();

    }

    /**
     * @brief Called by Android when the activity starts
     */
    @Override
    protected void onStart() {
        super.onStart();
        networkingController = new NetworkingController();
        networkingController.setJsonListener(this);
        networkingController.start();
    }

    /**
     * @brief Called by Android when the activity stops
     */
    @Override
    protected void onStop() {
        super.onStop();
        networkingController.stop();
        networkingController = null;
        if( audioTrack != null ) {
            audioTrack.stop();
        }
    }

    /**
     * @brief Determine if the tone should be on when app started
     * @return True if Tone should be on when app started.
     */
    private boolean getToneOnAtStartup() {
        boolean state = sharedPreferences.getBoolean( getString(R.string.default_tone_on), false);
        MainActivity.Log("Tone on at startup: "+state);
        return state;
    }

    /**
     * @brief Get the initial freq of the tone.
     * @return The freq in Hz
     */
    private int getDefaultToneHz() {
        String s = sharedPreferences.getString( getString(R.string.default_tone_hz), "750");
        return Integer.parseInt(s);
    }

    /**
     * @brief Get the tone step size in Hz
     * @return The tone step size per dB change in RX power level.
     */
    private int getToneStepHz() {
        String s = sharedPreferences.getString( getString(R.string.tone_step_hz), "25");
        return Integer.parseInt(s);
    }

    /**
     * @brief Called by Android to add the action bar.
     * @param menu
     * @return
     */
    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        // Inflate the menu; this adds items to the action bar if it is present.
        getMenuInflater().inflate(R.menu.menu_main, menu);
        return true;
    }

    /**
     * @brief Called by Android to handle clicks in the actions bar.
     * @param item
     * @return
     */
    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        // Handle action bar item clicks here. The action bar will
        // automatically handle clicks on the Home/Up button, so long
        // as you specify a parent activity in AndroidManifest.xml.
        int id = item.getItemId();

        if (id == R.id.action_settings) {
            Intent intent = new Intent(this, SettingsActivity.class);
            startActivity(intent);
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    /**
     * @brief Create a tone on the required freq.
     */
    private void createTone() {
        final int duration = 30; // duration of sound, a click is produced at the end of the duration so we set 30 seconds
        final int sampleRate = 22050; // Hz (maximum frequency is 7902.13Hz (B8))
        final int numSamples = duration * sampleRate;
        final double samples[] = new double[numSamples];
        final short buffer[] = new short[numSamples];
        for (int i = 0; i < numSamples; ++i)
        {
            samples[i] = Math.sin(2 * Math.PI * i / (sampleRate / freqHz)); // Sine wave
            buffer[i] = (short) (samples[i] * Short.MAX_VALUE);  // Higher amplitude increases volume
        }

        audioTrack = new AudioTrack(AudioManager.STREAM_MUSIC,
                sampleRate, AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT, buffer.length,
                AudioTrack.MODE_STATIC);

        audioTrack.write(buffer, 0, buffer.length);
        int frameCount = audioTrack.getBufferSizeInFrames();
        audioTrack.setLoopPoints(0, frameCount, -1);
    }

    /**
     * @brief Called when the tone up button is selected to increase the freq of the tone by one step.
     * @param view
     */
    public void toneUp(View view) {
        boolean restart = false;
        float stepHZ = getToneStepHz();
        freqHz = (int)(freqHz+stepHZ);
        updateTone();
    }

    /**
     * @brief Called when the tone up button is selected to decrease the freq of the tone by one step.
     * @param view
     */
    public void toneDown(View view) {
        boolean restart = false;
        float stepHZ = getToneStepHz();
        freqHz = (int)(freqHz-stepHZ);
        updateTone();
    }

    /**
     * @brief Called when the reset tone button is selected to set the tone to the configured default frequency.
     * @param view
     */
    public void resetTone(View view) {
        boolean restart = false;
        freqHz = getDefaultToneHz();
        updateTone();
    }

    /**
     * @brief Update the tone. This involves stopping (if running) and starting the tone.
     */
    private void updateTone() {
        boolean restart = false;
        if( audioTrack != null ) {
            if (audioTrack.getPlayState() == AudioTrack.PLAYSTATE_PLAYING) {
                audioTrack.stop();
                restart = true;
            }
            audioTrack.stop();
        }
        createTone();
        if( restart ) {
            audioTrack.play();
        }
    }

    /**
     * @brief Called when back button is pressed to shutdown app. Asks user if they are sure.
     */
    @Override
    public void onBackPressed() {
            AlertDialog.Builder builder = new AlertDialog.Builder(this);
            builder.setMessage("Are you sure you want to exit?")
                    .setCancelable(false)
                    .setPositiveButton("Yes", new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int id) {
                            finish();
                        }
                    })
                    .setNegativeButton("No", new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int id) {
                            dialog.cancel();
                        }
                    });
            AlertDialog alert = builder.create();
            alert.show();
    }

    /**
     * @brief Called to send text to Android log.
     * @param message
     */
    public static void Log(String message) {
        Log.e(Constants.APP_NAME, message);
    }


    /**
     * @brief This is called or every message received from the lb2120 python program.
     * @param device
     */
    public void jsonMsgReceived(JSONObject device) {
        float rxp = 0;
        if( active ) {
            try {
                rxp = device.getInt("RXP");


                rxpTextView.setText("RXP = "+rxp+" dBm");
                if (initialRXP == -1000) {
                    MainActivity.Log("rxp = " + rxp + " dB");
                    initialRXP = (int)rxp;
                    lastRXP = (int)rxp;
                    freqHz = getDefaultToneHz();
                    MainActivity.Log("Set default tone of "+freqHz+" Hz");
                    updateTone();
                    audioTrack.play();
                }

                int rxpChange = (int) (lastRXP - rxp);
                if (rxpChange != 0) {
                    int oldHz = freqHz;

                    MainActivity.Log("initialRXP      = "+initialRXP);
                    MainActivity.Log("rxp             = "+rxp);
                    MainActivity.Log("getToneStepHz() = "+getToneStepHz());
                    MainActivity.Log("rxpChange       = "+rxpChange);

                    freqHz = getDefaultToneHz() - (int)((initialRXP - (int)rxp) * getToneStepHz());
                    MainActivity.Log("Changed tone from " + oldHz + " Hz to " + freqHz + " Hz.");
                    updateTone();
                    audioTrack.play();
                    lastRXP = (int)rxp;
                }

            } catch (Exception e) {
                e.printStackTrace();
            }
        }
        else {
            if( audioTrack != null ) {
                audioTrack.stop();
            }
        }
    }

    /**
     * @brief Called when the on switch is changed.
     * @param compoundButton
     * @param b
     */
    @Override
    public void onCheckedChanged(CompoundButton compoundButton, boolean b) {
        active = b;
        if( active && audioTrack != null ) {
            audioTrack.play();
        }
    }
}