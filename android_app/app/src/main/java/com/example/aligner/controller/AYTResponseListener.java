package com.example.aligner.controller;

import org.json.JSONObject;

import java.io.IOException;
import java.net.ServerSocket;
import java.util.Vector;

import com.example.aligner.model.Constants;
import com.example.aligner.view.MainActivity;
import java.net.Socket;
import java.io.InputStream;
import java.io.DataInputStream;
import org.json.JSONObject;

/**
 * @brief Responisble for receiving messages from clients.
 */
public class AYTResponseListener extends Thread {
    Vector<JSONListener> jsonListenerList;
    Vector<Socket> activeSocketList;
    JSONObject jsonO;
    ServerSocket serverSocket;
    Socket socket;
    boolean active;

    /**
     * @brief Constructor
     */
    public AYTResponseListener(ServerSocket serverSocket) {
        this.serverSocket=serverSocket;
        jsonListenerList = new Vector<JSONListener>();
        activeSocketList = new Vector<Socket>();
    }

    /**
     * @brief Handle a connected socket.
     * @param socket A Socket instance.
     */
    private void handleSocket(Socket socket) {
        byte[]  rxBuffer;
        JSONObject jsonObject = null;
        activeSocketList.add(socket);

        MainActivity.Log("Client connected to server.");
        try {
            rxBuffer = new byte[4096];
            DataInputStream dis = new DataInputStream( socket.getInputStream() );
            while(active) {
                int msgLength = dis.readInt();
                if( msgLength > 2 ) {
                    if (msgLength > rxBuffer.length) {
                        rxBuffer = new byte[msgLength];
                    }
                    dis.readFully(rxBuffer, 0, msgLength);
                    MainActivity.Log("Received " + msgLength + " byte message.");
                    if (msgLength > 0) {
                        String jsonStr = new String(rxBuffer, 0, msgLength);
                        jsonO = new JSONObject(jsonStr);
                        MainActivity.Log("Received Message: "+jsonO);
                        notifyLiseners(jsonO);
                    }
                }
            }
        }
        catch(Exception e) {
            e.printStackTrace();
        }
        finally {
            activeSocketList.remove(socket);
        }
    }

    public void run() {
        listen();
    }

    /**
     * @brief A blocking call that will listen for Beacon messages and notify beaconListener
     * objects when they are received.
     */
    public void listen() {
        active = true;
        activeSocketList.remove(socket);
        try {
            //Loop to listen for AYT messages
            while(active) {
                MainActivity.Log("Listening for TCP connection to server port "+serverSocket.getLocalPort());
                socket = serverSocket.accept();
                handleSocket(socket);
            }
        }
        catch(Exception e) {
            e.printStackTrace();
        }
    }

    /**
     * @brief Shutdown the server. This will close the server socket if we have a reference to a bound socket.
     */
    public void shutdown() {
        MainActivity.Log("AYTResponseReceiver.shutdown()");
        active = false;
        for(Socket socket : activeSocketList ) {
            try {
                socket.close();
            }
            catch(Exception e) {
                e.printStackTrace();
            }
        }
        activeSocketList = new Vector<Socket>();
    }

    private void notifyLiseners(JSONObject jsonObject) {
        if (jsonListenerList != null) {
            for (JSONListener jsonListener : jsonListenerList) {
                jsonListener.jsonMsgReceived(jsonObject);
            }
        }
    }

    /**
     * @brief Add to the list of JSONListener objects.
     * @param deviceListener The object to be notified of messages received from devices.
     */
    public void addJSONListener(JSONListener deviceListener) {
        jsonListenerList.add(deviceListener);
    }

    /**
     * @brief Remove a JSONListener object from the list of of deviceListener objects.
     * @param deviceListener The object to be notified of messages received from devices.
     */
    public void removeJSONListener(JSONListener deviceListener) {
        jsonListenerList.remove(deviceListener);
    }

    /**
     * @brief Remove all deviceListener objects
     */
    public void removeAllJSONListeners() {
        jsonListenerList.removeAllElements();
    }



}
