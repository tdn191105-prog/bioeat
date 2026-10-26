package ru.rospit.app;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // плагин внешних ссылок (СБП, банковские приложения) регистрируем до запуска моста
        registerPlugin(ExternalLinksPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
