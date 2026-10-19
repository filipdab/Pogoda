# Pogoda

Okienkowa aplikacja pogodowa dla Windows (Python + tkinter) z wyszukiwaniem i wyborem miasta.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)

## Funkcje
- wyszukiwanie miasta (geokodowanie Open-Meteo) i wybór z listy wyników
- bieżące warunki: temperatura, odczuwalna, wilgotność, wiatr, ciśnienie, opad, wschód/zachód słońca
- prognoza na 7 dni z prawdopodobieństwem i sumą opadów
- zapamiętywanie ostatniego miasta (`%APPDATA%\PogodaApp\config.json`)
- automatyczne odświeżanie co 15 min (F5 – ręcznie)
- okno „O aplikacji” (F1)

## Uruchomienie
Nie wymaga dodatkowych bibliotek – tylko Python 3.8+.

```
pythonw pogoda.py
```

### Plik .exe
```
pip install pyinstaller
pyinstaller --onefile --noconsole pogoda.py
```

## Dane
Prognoza i geokodowanie: [Open-Meteo.com](https://open-meteo.com) (CC BY 4.0) – bez klucza API.

## Autor
Filip – [filipdab@gmail.com](mailto:filipdab@gmail.com) · [github.com/filipdab](https://github.com/filipdab)
