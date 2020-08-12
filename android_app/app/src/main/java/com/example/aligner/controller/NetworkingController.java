package com.example.aligner.controller;

import com.example.aligner.model.Constants;
import com.example.aligner.view.MainActivity;

import org.json.JSONObject;

import java.io.IOException;
import java.net.DatagramSocket;
import java.util.Timer;
import java.util.TimerTask;
import java.net.ServerSocket;

public class NetworkingController {
    Timer aytTXTimer;
    AYTTransmitter aytTransmitter;
    DatagramSocket udpBCastSocket;
    ServerSocket   serverSocket;
    AYTResponseListener aytResponseListener;
    JSONListener jsonListener;

    /**
     * @brief Start all networking threads and timers.
     */
    public void start() {
        try {
            udpBCastSocket = new DatagramSocket(Constants.UDP_MULTICAST_PORT);

            //Bind a TCP server socket socket on which we will receive responses to
            //the UDP broadcast AYT messages.
            serverSocket = new ServerSocket(0);

            aytResponseListener = new AYTResponseListener(serverSocket);
            if( jsonListener != null ) {
                aytResponseListener.addJSONListener(jsonListener);
            }
            aytResponseListener.start();

            aytTransmitter = new AYTTransmitter();
            aytTransmitter.setTCPServerPort(serverSocket.getLocalPort());

            //Setup a timer to timeout units we have lost contact with
            aytTXTimer = new Timer();
            AYTTXTask aytTXTask = new AYTTXTask();
            aytTXTimer.schedule(aytTXTask, 0, Constants.AYT_PERIOD_MS);

        }
        catch( IOException e ) {
            MainActivity.Log("LAN ERROR: "+e.getLocalizedMessage());
        }
    }

    /**
     * @brief Stop all networking threads and timers.
     */
    public void stop() {
        if( aytResponseListener != null ) {
            aytResponseListener.shutdown();
            aytResponseListener = null;
        }
        if( aytTXTimer != null ) {
            aytTXTimer.cancel();
            aytTXTimer = null;
        }
        if( serverSocket != null ) {
            try {
                serverSocket.close();
            }
            catch(Exception e) {}
            serverSocket= null;
        }
    }

    /**
     * @brief Task called periodically to broadcast an AYT message.
     */
    class AYTTXTask extends TimerTask {

        public void run() {
            if( aytTransmitter != null ) {
                aytTransmitter.sendAYTMessage(udpBCastSocket);
            }

        }

    }

    /**
     * @brief Add a listener for received JSON messages.
     * @param jsonListener
     */
    public void setJsonListener(JSONListener jsonListener) {
        this.jsonListener = jsonListener;
    }

}
