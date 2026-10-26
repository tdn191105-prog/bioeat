package ru.rospit.app;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.widget.Toast;

import com.getcapacitor.Plugin;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.net.URISyntaxException;

/**
 * Ссылки оплаты, которые WebView открыть не может.
 *
 * СБП отдаёт ссылку https://qr.nspk.ru/… (Android показывает выбор банка) или
 * сразу схему банка bankXXXXXXXXXX:// / intent://. Такие ссылки уходят в систему —
 * в банковское приложение. Страницы ЮKassa и 3-D Secure банка остаются внутри
 * WebView: после оплаты банк вернёт студента на return_url прямо в приложение.
 */
@CapacitorPlugin(name = "ExternalLinks")
public class ExternalLinksPlugin extends Plugin {

    @Override
    public Boolean shouldOverrideLoad(Uri url) {
        String scheme = url.getScheme() == null ? "" : url.getScheme().toLowerCase();
        String host = url.getHost() == null ? "" : url.getHost().toLowerCase();

        if (scheme.equals("http") || scheme.equals("https")) {
            if (host.equals("qr.nspk.ru") || host.endsWith(".nspk.ru") || host.equals("sub.nspk.ru")) {
                openExternal(new Intent(Intent.ACTION_VIEW, url));
                return true;
            }
            // всё остальное по http(s) — включая 3-D Secure любого банка — грузим в WebView
            return false;
        }

        if (scheme.equals("intent")) {
            try {
                Intent intent = Intent.parseUri(url.toString(), Intent.URI_INTENT_SCHEME);
                intent.addCategory(Intent.CATEGORY_BROWSABLE);
                intent.setComponent(null);
                intent.setSelector(null);
                try {
                    getActivity().startActivity(intent);
                } catch (ActivityNotFoundException e) {
                    String fallback = intent.getStringExtra("browser_fallback_url");
                    if (fallback != null) {
                        openExternal(new Intent(Intent.ACTION_VIEW, Uri.parse(fallback)));
                    } else if (intent.getPackage() != null) {
                        openExternal(new Intent(Intent.ACTION_VIEW,
                                Uri.parse("market://details?id=" + intent.getPackage())));
                    } else {
                        notFound();
                    }
                }
            } catch (URISyntaxException e) {
                notFound();
            }
            return true;
        }

        // bank100000000111://, sberpay://, tinkoffbank:// и другие схемы банков
        openExternal(new Intent(Intent.ACTION_VIEW, url));
        return true;
    }

    private void openExternal(Intent intent) {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            getActivity().startActivity(intent);
        } catch (ActivityNotFoundException e) {
            notFound();
        }
    }

    private void notFound() {
        getActivity().runOnUiThread(() -> Toast.makeText(getContext(),
                "Не найдено приложение банка. Выберите оплату картой.", Toast.LENGTH_LONG).show());
    }
}
