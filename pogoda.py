#!/usr/bin/env python3
"""
Pogoda – okienkowa aplikacja pogodowa dla Windows.
Dane: Open-Meteo (https://open-meteo.com) – darmowe, bez klucza API.
Wymagania: Python 3.8+ (tylko biblioteka standardowa).
Uruchomienie: python pogoda.py   (lub pythonw pogoda.py – bez konsoli)
"""

import json
import os
import threading
import tkinter as tk
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from tkinter import ttk

APP_NAME = "Pogoda"
APP_VERSION = "1.1.0"
AUTHOR = "Filip"
AUTHOR_EMAIL = "filipdab@gmail.com"
AUTHOR_GITHUB = "https://github.com/filipdab"

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REFRESH_MS = 15 * 60 * 1000  # automatyczne odświeżanie co 15 min

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PogodaApp")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CITY = {"name": "Warszawa", "admin1": "Mazowieckie", "country": "Polska",
                "latitude": 52.2298, "longitude": 21.0118}

# Kody pogody WMO -> (opis, ikona)
WMO = {
    0: ("Bezchmurnie", "☀️"), 1: ("Przeważnie pogodnie", "🌤️"),
    2: ("Częściowe zachmurzenie", "⛅"), 3: ("Pochmurno", "☁️"),
    45: ("Mgła", "🌫️"), 48: ("Mgła osadzająca szadź", "🌫️"),
    51: ("Lekka mżawka", "🌦️"), 53: ("Mżawka", "🌦️"), 55: ("Gęsta mżawka", "🌧️"),
    56: ("Marznąca mżawka", "🌧️"), 57: ("Gęsta marznąca mżawka", "🌧️"),
    61: ("Słaby deszcz", "🌦️"), 63: ("Deszcz", "🌧️"), 65: ("Ulewa", "🌧️"),
    66: ("Marznący deszcz", "🌧️"), 67: ("Silny marznący deszcz", "🌧️"),
    71: ("Słaby śnieg", "🌨️"), 73: ("Śnieg", "🌨️"), 75: ("Intensywny śnieg", "❄️"),
    77: ("Ziarna śniegu", "🌨️"),
    80: ("Przelotny deszcz", "🌦️"), 81: ("Przelotne opady", "🌧️"), 82: ("Gwałtowne ulewy", "⛈️"),
    85: ("Przelotny śnieg", "🌨️"), 86: ("Silny przelotny śnieg", "❄️"),
    95: ("Burza", "⛈️"), 96: ("Burza z gradem", "⛈️"), 99: ("Silna burza z gradem", "⛈️"),
}
DNI = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Nd"]
KIERUNKI = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def http_json(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "PogodaApp/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def search_cities(name):
    data = http_json(GEO_URL, {"name": name, "count": 10, "language": "pl", "format": "json"})
    return data.get("results", []) or []


def get_forecast(lat, lon):
    return http_json(FORECAST_URL, {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 7,
        "wind_speed_unit": "kmh",
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                   "weather_code,wind_speed_10m,wind_direction_10m,pressure_msl,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_sum,precipitation_probability_max,sunrise,sunset",
    })


def city_label(c):
    parts = [c.get("name", "")]
    if c.get("admin1"):
        parts.append(c["admin1"])
    if c.get("country"):
        parts.append(c["country"])
    return ", ".join(parts)


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"city": DEFAULT_CITY}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class WeatherApp(tk.Tk):
    BG = "#1e2533"
    CARD = "#2a3345"
    FG = "#e8ecf3"
    MUTED = "#9aa6bd"
    ACCENT = "#5aa9ff"

    def __init__(self):
        super().__init__()
        self.title("Pogoda")
        self.geometry("720x520")
        self.minsize(640, 480)
        self.configure(bg=self.BG)

        self.cfg = load_config()
        self.city = self.cfg.get("city", DEFAULT_CITY)
        self.results = []
        self.refresh_job = None

        self._style()
        self._build()
        self.load_weather()

    # ---------- UI ----------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=self.BG)
        s.configure("Card.TFrame", background=self.CARD)
        s.configure("TButton", padding=6)
        s.configure("TCombobox", padding=4)

    def _lbl(self, parent, text="", size=10, bold=False, color=None, bg=None):
        return tk.Label(parent, text=text, fg=color or self.FG, bg=bg or self.CARD,
                        font=("Segoe UI", size, "bold" if bold else "normal"))

    def _build(self):
        # Menu
        menubar = tk.Menu(self)
        m_app = tk.Menu(menubar, tearoff=0)
        m_app.add_command(label="Odśwież", accelerator="F5", command=self.load_weather)
        m_app.add_separator()
        m_app.add_command(label="Zakończ", command=self.destroy)
        menubar.add_cascade(label="Aplikacja", menu=m_app)
        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="O aplikacji…", accelerator="F1", command=self.show_about)
        menubar.add_cascade(label="Pomoc", menu=m_help)
        self.config(menu=menubar)
        self.bind("<F1>", lambda e: self.show_about())
        self.bind("<F5>", lambda e: self.load_weather())

        # Pasek wyszukiwania
        top = ttk.Frame(self, padding=(12, 12, 12, 6))
        top.pack(fill="x")
        self.search_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.search_var, font=("Segoe UI", 11))
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.do_search())
        ttk.Button(top, text="Szukaj", command=self.do_search).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="⟳", width=3, command=self.load_weather).pack(side="left", padx=(6, 0))

        # Lista wyników wyszukiwania
        res = ttk.Frame(self, padding=(12, 0, 12, 6))
        res.pack(fill="x")
        self.combo = ttk.Combobox(res, state="readonly", font=("Segoe UI", 10))
        self.combo.pack(fill="x")
        self.combo.set("Wpisz miasto i naciśnij Enter, potem wybierz z listy")
        self.combo.bind("<<ComboboxSelected>>", self.on_city_selected)

        # Bieżąca pogoda
        cur = ttk.Frame(self, style="Card.TFrame", padding=16)
        cur.pack(fill="x", padx=12, pady=6)
        left = tk.Frame(cur, bg=self.CARD)
        left.pack(side="left", fill="y")
        self.city_lbl = self._lbl(left, size=14, bold=True)
        self.city_lbl.pack(anchor="w")
        row = tk.Frame(left, bg=self.CARD)
        row.pack(anchor="w", pady=(4, 0))
        self.icon_lbl = self._lbl(row, size=40)
        self.icon_lbl.pack(side="left")
        self.temp_lbl = self._lbl(row, size=40, bold=True)
        self.temp_lbl.pack(side="left", padx=(8, 0))
        self.desc_lbl = self._lbl(left, size=11, color=self.MUTED)
        self.desc_lbl.pack(anchor="w")

        right = tk.Frame(cur, bg=self.CARD)
        right.pack(side="right", fill="y")
        self.details = {}
        for key in ["Odczuwalna", "Wilgotność", "Wiatr", "Ciśnienie", "Opad", "Wschód / zachód"]:
            r = tk.Frame(right, bg=self.CARD)
            r.pack(anchor="e", fill="x")
            self._lbl(r, key + ":", color=self.MUTED).pack(side="left")
            v = self._lbl(r, bold=True)
            v.pack(side="right", padx=(12, 0))
            self.details[key] = v

        # Prognoza 7 dni
        self.days_frame = ttk.Frame(self, padding=(12, 6, 12, 6))
        self.days_frame.pack(fill="both", expand=True)

        # Status
        self.status = tk.Label(self, text="", fg=self.MUTED, bg=self.BG,
                               font=("Segoe UI", 9), anchor="w")
        self.status.pack(fill="x", padx=12, pady=(0, 8))

    # ---------- Wyszukiwanie ----------
    def do_search(self):
        q = self.search_var.get().strip()
        if not q:
            return
        self.status.config(text=f"Szukam „{q}”…")
        self._bg(lambda: search_cities(q), self._on_search_done)

    def _on_search_done(self, results, err):
        if err:
            self.status.config(text=f"Błąd wyszukiwania: {err}")
            return
        self.results = results
        if not results:
            self.combo["values"] = []
            self.combo.set("Nie znaleziono miasta")
            self.status.config(text="Brak wyników")
            return
        self.combo["values"] = [city_label(c) for c in results]
        self.combo.current(0)
        self.status.config(text=f"Znaleziono {len(results)} – wybierz z listy")
        if len(results) == 1:
            self.on_city_selected()
        else:
            self.combo.event_generate("<Button-1>")  # rozwiń listę

    def on_city_selected(self, _=None):
        i = self.combo.current()
        if i < 0 or i >= len(self.results):
            return
        c = self.results[i]
        self.city = {k: c.get(k) for k in ("name", "admin1", "country", "latitude", "longitude")}
        self.cfg["city"] = self.city
        save_config(self.cfg)
        self.load_weather()

    # ---------- Pogoda ----------
    def load_weather(self):
        if self.refresh_job:
            self.after_cancel(self.refresh_job)
        self.status.config(text="Pobieram prognozę…")
        c = self.city
        self._bg(lambda: get_forecast(c["latitude"], c["longitude"]), self._on_weather)
        self.refresh_job = self.after(REFRESH_MS, self.load_weather)

    def _on_weather(self, data, err):
        if err:
            self.status.config(text=f"Błąd pobierania: {err}")
            return
        cur, daily = data["current"], data["daily"]
        desc, icon = WMO.get(cur["weather_code"], ("—", "❔"))

        self.title(f"Pogoda – {self.city['name']}")
        self.city_lbl.config(text=city_label(self.city))
        self.icon_lbl.config(text=icon)
        self.temp_lbl.config(text=f"{cur['temperature_2m']:.0f}°C")
        self.desc_lbl.config(text=desc)

        wd = KIERUNKI[round(cur["wind_direction_10m"] / 45) % 8]
        self.details["Odczuwalna"].config(text=f"{cur['apparent_temperature']:.0f}°C")
        self.details["Wilgotność"].config(text=f"{cur['relative_humidity_2m']}%")
        self.details["Wiatr"].config(text=f"{cur['wind_speed_10m']:.0f} km/h {wd}")
        self.details["Ciśnienie"].config(text=f"{cur['pressure_msl']:.0f} hPa")
        self.details["Opad"].config(text=f"{cur['precipitation']:.1f} mm")
        sr = daily["sunrise"][0][-5:]
        ss = daily["sunset"][0][-5:]
        self.details["Wschód / zachód"].config(text=f"{sr} / {ss}")

        for w in self.days_frame.winfo_children():
            w.destroy()
        for i, day in enumerate(daily["time"]):
            d = datetime.strptime(day, "%Y-%m-%d")
            name = "Dziś" if i == 0 else DNI[d.weekday()]
            ddesc, dicon = WMO.get(daily["weather_code"][i], ("—", "❔"))
            card = tk.Frame(self.days_frame, bg=self.CARD, padx=6, pady=10)
            card.grid(row=0, column=i, sticky="nsew", padx=3)
            self.days_frame.columnconfigure(i, weight=1)
            self._lbl(card, name, 11, True).pack()
            self._lbl(card, d.strftime("%d.%m"), 9, color=self.MUTED).pack()
            self._lbl(card, dicon, 24).pack(pady=4)
            self._lbl(card, f"{daily['temperature_2m_max'][i]:.0f}°", 12, True).pack()
            self._lbl(card, f"{daily['temperature_2m_min'][i]:.0f}°", 10, color=self.MUTED).pack()
            prob = daily["precipitation_probability_max"][i]
            psum = daily["precipitation_sum"][i]
            self._lbl(card, f"💧 {prob if prob is not None else '–'}%", 9, color=self.ACCENT).pack(pady=(4, 0))
            self._lbl(card, f"{psum:.1f} mm" if psum is not None else "", 9, color=self.MUTED).pack()
            tip = tk.Label(card, text=ddesc, fg=self.MUTED, bg=self.CARD,
                           font=("Segoe UI", 8), wraplength=80)
            tip.pack(pady=(4, 0))

        self.status.config(text=f"Zaktualizowano {datetime.now():%H:%M:%S} · dane: Open-Meteo · "
                                f"odświeżanie co {REFRESH_MS // 60000} min")

    # ---------- O aplikacji ----------
    def show_about(self):
        if getattr(self, "_about", None) and self._about.winfo_exists():
            self._about.lift()
            return
        win = tk.Toplevel(self)
        self._about = win
        win.title(f"O aplikacji {APP_NAME}")
        win.configure(bg=self.CARD, padx=28, pady=20)
        win.resizable(False, False)
        win.transient(self)

        def lbl(text, size=10, bold=False, color=None, pady=0):
            l = tk.Label(win, text=text, fg=color or self.FG, bg=self.CARD,
                         font=("Segoe UI", size, "bold" if bold else "normal"), justify="center")
            l.pack(pady=pady)
            return l

        def link(text, url):
            l = lbl(text, color=self.ACCENT)
            l.configure(cursor="hand2", font=("Segoe UI", 10, "underline"))
            l.bind("<Button-1>", lambda e: webbrowser.open(url))

        lbl("⛅", 40)
        lbl(APP_NAME, 18, True)
        lbl(f"Wersja {APP_VERSION}", 9, color=self.MUTED, pady=(0, 10))
        lbl("Prosta okienkowa prognoza pogody z wyborem miasta.", 10)
        lbl("Autor", 9, color=self.MUTED, pady=(14, 0))
        lbl(AUTHOR, 12, True)
        link(AUTHOR_EMAIL, f"mailto:{AUTHOR_EMAIL}")
        link(AUTHOR_GITHUB.replace("https://", ""), AUTHOR_GITHUB)
        lbl("Dane pogodowe", 9, color=self.MUTED, pady=(14, 0))
        link("Open-Meteo.com (CC BY 4.0)", "https://open-meteo.com")
        lbl(f"© {datetime.now().year} {AUTHOR}", 9, color=self.MUTED, pady=(14, 8))
        ttk.Button(win, text="Zamknij", command=win.destroy).pack()
        win.bind("<Escape>", lambda e: win.destroy())

        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()
        win.focus_set()

    # ---------- wątek w tle ----------
    def _bg(self, fn, callback):
        def worker():
            try:
                res, err = fn(), None
            except Exception as e:
                res, err = None, e
            self.after(0, lambda: callback(res, err))
        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    WeatherApp().mainloop()
