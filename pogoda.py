#!/usr/bin/env python3
"""
Pogoda – okienkowa aplikacja pogodowa dla Windows.

Dane: Open-Meteo (https://open-meteo.com) – darmowe, bez klucza API.
Wymagania: Python 3.8+. Opcjonalnie: pystray + Pillow (ikona w zasobniku).

Uruchomienie:  pythonw pogoda.py            (okno)
               pythonw pogoda.py --minimized (start w zasobniku / zminimalizowana)

Autor: Filip <filipdab@gmail.com> – https://github.com/filipdab
"""

import json
import math
import os
import queue
import sys
import threading
import tkinter as tk
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from tkinter import ttk, messagebox

try:
    import winreg  # tylko Windows
except ImportError:
    winreg = None

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False

# ---------------------------------------------------------------- stałe
APP_NAME = "Pogoda"
APP_VERSION = "2.0.0"
AUTHOR = "Filip"
AUTHOR_EMAIL = "filipdab@gmail.com"
AUTHOR_GITHUB = "https://github.com/filipdab"
PROJECT_URL = "https://github.com/filipdab/Pogoda"

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
IP_URLS = ["https://ipapi.co/json/", "https://ipwho.is/"]

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PogodaApp")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
CACHE_FILE = os.path.join(CONFIG_DIR, "cache.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULT_CITY = {"name": "Warszawa", "admin1": "Mazowieckie", "country": "Polska",
                "latitude": 52.2298, "longitude": 21.0118}

DEFAULT_CFG = {
    "city": None,
    "favorites": [],
    "temp_unit": "C",          # C / F
    "wind_unit": "kmh",        # kmh / ms / kn / mph
    "theme": "system",         # system / light / dark
    "refresh_min": 15,
    "minimize_to_tray": True,
    "alerts": {"enabled": True, "storm": True, "gust": 60, "frost": 0, "rain": 20},
    "widget_pos": None,
}

TEMP_UNITS = {"C": ("celsius", "°C"), "F": ("fahrenheit", "°F")}
WIND_UNITS = {"kmh": "km/h", "ms": "m/s", "kn": "kn", "mph": "mph"}
WIND_TO_KMH = {"kmh": 1.0, "ms": 3.6, "kn": 1.852, "mph": 1.609344}
THEME_NAMES = {"system": "Systemowy", "light": "Jasny", "dark": "Ciemny"}

THEMES = {
    "dark": dict(bg="#1e2533", card="#2a3345", fg="#e8ecf3", muted="#9aa6bd",
                 accent="#5aa9ff", rain="#3d7cc9", warn="#ffb347", grid="#3a4458"),
    "light": dict(bg="#eef2f7", card="#ffffff", fg="#1d2433", muted="#5f6b80",
                  accent="#1f6fd1", rain="#8db8ea", warn="#b85c00", grid="#dbe2ec"),
}

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
NIGHT_ICONS = {0: "🌙", 1: "🌙"}
STORM_CODES = {95, 96, 99}
DNI = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Nd"]
KIERUNKI = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


# ---------------------------------------------------------------- pomocnicze
def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def http_json(url, params=None, timeout=15):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def search_cities(name):
    data = http_json(GEO_URL, {"name": name, "count": 10, "language": "pl", "format": "json"})
    return data.get("results", []) or []


def get_forecast(lat, lon, cfg):
    return http_json(FORECAST_URL, {
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "past_days": 1, "forecast_days": 7,
        "temperature_unit": TEMP_UNITS[cfg["temp_unit"]][0],
        "wind_speed_unit": cfg["wind_unit"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,"
                   "wind_speed_10m,wind_direction_10m,wind_gusts_10m,pressure_msl,precipitation,"
                   "cloud_cover,visibility,uv_index,is_day",
        "hourly": "temperature_2m,precipitation,precipitation_probability,weather_code,"
                  "pressure_msl,wind_gusts_10m,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                 "precipitation_probability_max,sunrise,sunset,daylight_duration,"
                 "uv_index_max,wind_gusts_10m_max",
    })


def get_air(lat, lon):
    return http_json(AIR_URL, {"latitude": lat, "longitude": lon, "timezone": "auto",
                               "current": "european_aqi,pm2_5,pm10"})


def ip_locate():
    last = None
    for url in IP_URLS:
        try:
            d = http_json(url, timeout=8)
            lat, lon = d.get("latitude"), d.get("longitude")
            if lat is None or lon is None:
                continue
            return {"name": d.get("city") or "Moja lokalizacja",
                    "admin1": d.get("region") or "",
                    "country": d.get("country_name") or d.get("country") or "",
                    "latitude": float(lat), "longitude": float(lon)}
        except Exception as e:
            last = e
    raise RuntimeError(f"nie udało się ustalić lokalizacji ({last})")


def city_label(c):
    return ", ".join(p for p in (c.get("name"), c.get("admin1"), c.get("country")) if p)


def same_city(a, b):
    return (a and b and round(a["latitude"], 2) == round(b["latitude"], 2)
            and round(a["longitude"], 2) == round(b["longitude"], 2))


def moon_phase(dt):
    """Zwraca (nazwa, ikona, oświetlenie %) – przybliżenie astronomiczne."""
    synodic = 29.530588853
    age = ((dt - datetime(2000, 1, 6, 18, 14)).total_seconds() / 86400) % synodic
    illum = round((1 - math.cos(2 * math.pi * age / synodic)) / 2 * 100)
    phases = [(1.85, "Nów", "🌑"), (5.54, "Przybywający sierp", "🌒"),
              (9.23, "Pierwsza kwadra", "🌓"), (12.92, "Przybywający garb", "🌔"),
              (16.61, "Pełnia", "🌕"), (20.30, "Ubywający garb", "🌖"),
              (23.99, "Ostatnia kwadra", "🌗"), (27.68, "Ubywający sierp", "🌘"),
              (synodic + 1, "Nów", "🌑")]
    for limit, name, icon in phases:
        if age < limit:
            return name, icon, illum


def uv_label(uv):
    if uv is None:
        return "–"
    for lim, txt in ((3, "niski"), (6, "umiarkowany"), (8, "wysoki"), (11, "bardzo wysoki")):
        if uv < lim:
            return f"{uv:.0f} ({txt})"
    return f"{uv:.0f} (ekstremalny)"


def aqi_label(aqi):
    if aqi is None:
        return "–"
    for lim, txt in ((20, "bardzo dobra"), (40, "dobra"), (60, "umiarkowana"),
                     (80, "zła"), (100, "bardzo zła")):
        if aqi < lim:
            return f"{aqi:.0f} – {txt}"
    return f"{aqi:.0f} – skrajnie zła"


def windows_light_theme():
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 1
    except OSError:
        return False


def autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    if os.path.exists(pyw):
        py = pyw
    return f'"{py}" "{os.path.abspath(__file__)}" --minimized'


def get_autostart():
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on):
    if not winreg:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    stored = load_json(CONFIG_FILE, {})
    for k, v in stored.items():
        if k == "alerts" and isinstance(v, dict):
            cfg["alerts"].update(v)
        elif k in cfg:
            cfg[k] = v
    return cfg


# ---------------------------------------------------------------- aplikacja
class WeatherApp(tk.Tk):
    def __init__(self, start_minimized=False):
        super().__init__()
        self.cfg = load_config()
        self.city = self.cfg.get("city")
        self.results, self.data, self.air = [], None, None
        self.offline_ts = None
        self.refresh_job = None
        self.widget = None
        self.tray = None
        self.notified = set()
        self.active_alerts = []
        self._q = queue.Queue()
        self._tray_hint_shown = False

        self.title(APP_NAME)
        self.geometry("900x860")
        self.minsize(820, 780)
        try:
            self.iconbitmap(resource_path(os.path.join("assets", "pogoda.ico")))
        except Exception:
            pass

        self._apply_theme(rebuild=False)
        self._build_menu()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll)
        self._start_tray()

        if self.city:
            self.load_weather()
        else:
            self.locate_by_ip(first_run=True)

        if start_minimized:
            if self.tray:
                self.withdraw()
            else:
                self.iconify()

    # ======================================================== wygląd
    def _apply_theme(self, rebuild=True):
        mode = self.cfg["theme"]
        if mode == "system":
            mode = "light" if windows_light_theme() else "dark"
        self.T = THEMES[mode]
        T = self.T
        self.configure(bg=T["bg"])
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=T["bg"], foreground=T["fg"], font=("Segoe UI", 10))
        s.configure("TFrame", background=T["bg"])
        s.configure("Card.TFrame", background=T["card"])
        s.configure("TButton", padding=5, background=T["card"], foreground=T["fg"],
                    bordercolor=T["grid"], lightcolor=T["card"], darkcolor=T["card"])
        s.map("TButton", background=[("active", T["grid"])])
        s.configure("Fav.TButton", padding=(8, 2))
        s.configure("TEntry", fieldbackground=T["card"], foreground=T["fg"],
                    insertcolor=T["fg"], bordercolor=T["grid"])
        s.configure("TCombobox", fieldbackground=T["card"], background=T["card"],
                    foreground=T["fg"], arrowcolor=T["fg"], bordercolor=T["grid"])
        s.map("TCombobox", fieldbackground=[("readonly", T["card"])],
              foreground=[("readonly", T["fg"])], selectbackground=[("readonly", T["card"])],
              selectforeground=[("readonly", T["fg"])])
        s.configure("TSpinbox", fieldbackground=T["card"], foreground=T["fg"],
                    background=T["card"], arrowcolor=T["fg"])
        for w in ("TCheckbutton", "TRadiobutton", "TLabel"):
            s.configure(w, background=T["card"], foreground=T["fg"])
            s.map(w, background=[("active", T["card"])])
        s.configure("TLabelframe", background=T["card"], bordercolor=T["grid"])
        s.configure("TLabelframe.Label", background=T["card"], foreground=T["accent"],
                    font=("Segoe UI", 10, "bold"))
        self.option_add("*TCombobox*Listbox.background", T["card"])
        self.option_add("*TCombobox*Listbox.foreground", T["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", T["accent"])
        if rebuild:
            widget_open = bool(self.widget and self.widget.winfo_exists())
            if widget_open:
                self.close_widget(show_main=False)
            for w in self.winfo_children():
                if not isinstance(w, (tk.Toplevel, tk.Menu)):
                    w.destroy()
            self._build()
            self.render()
            if widget_open:
                self.open_widget()

    def _lbl(self, parent, text="", size=10, bold=False, color=None, bg=None, **kw):
        return tk.Label(parent, text=text, fg=color or self.T["fg"], bg=bg or self.T["card"],
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kw)

    # ======================================================== budowa UI
    def _build_menu(self):
        mb = tk.Menu(self)
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Odśwież", accelerator="F5", command=self.load_weather)
        m.add_command(label="Moja lokalizacja (IP)", command=self.locate_by_ip)
        m.add_command(label="Ustawienia…", accelerator="Ctrl+,", command=self.show_settings)
        m.add_separator()
        m.add_command(label="Zakończ", accelerator="Ctrl+Q", command=self.quit_app)
        mb.add_cascade(label="Aplikacja", menu=m)
        v = tk.Menu(mb, tearoff=0)
        v.add_command(label="Tryb widżetu", accelerator="Ctrl+W", command=self.toggle_widget)
        mb.add_cascade(label="Widok", menu=v)
        h = tk.Menu(mb, tearoff=0)
        h.add_command(label="O aplikacji…", accelerator="F1", command=self.show_about)
        h.add_command(label="Strona projektu", command=lambda: webbrowser.open(PROJECT_URL))
        mb.add_cascade(label="Pomoc", menu=h)
        self.config(menu=mb)
        self.bind("<F1>", lambda e: self.show_about())
        self.bind("<F5>", lambda e: self.load_weather())
        self.bind("<Control-comma>", lambda e: self.show_settings())
        self.bind("<Control-q>", lambda e: self.quit_app())
        self.bind("<Control-w>", lambda e: self.toggle_widget())

    def _build(self):
        T = self.T
        # --- wyszukiwanie
        top = ttk.Frame(self, padding=(12, 10, 12, 4))
        top.pack(fill="x")
        self.search_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.search_var, font=("Segoe UI", 11))
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.do_search())
        ttk.Button(top, text="Szukaj", command=self.do_search).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="📍", width=3, command=self.locate_by_ip).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="⟳", width=3, command=self.load_weather).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="⚙", width=3, command=self.show_settings).pack(side="left", padx=(6, 0))

        res = ttk.Frame(self, padding=(12, 0, 12, 4))
        res.pack(fill="x")
        self.combo = ttk.Combobox(res, state="readonly")
        self.combo.pack(fill="x")
        self.combo.set("Wpisz miasto i naciśnij Enter, potem wybierz z listy")
        self.combo.bind("<<ComboboxSelected>>", self.on_city_selected)

        # --- ulubione
        self.fav_frame = ttk.Frame(self, padding=(12, 2, 12, 2))
        self.fav_frame.pack(fill="x")

        # --- ostrzeżenia
        self.alert_lbl = tk.Label(self, text="", fg=T["bg"], bg=T["warn"], anchor="w",
                                  font=("Segoe UI", 10, "bold"), padx=10, pady=4, justify="left")

        # --- bieżąca pogoda
        self.cur_frame = ttk.Frame(self, style="Card.TFrame", padding=14)
        self.cur_frame.pack(fill="x", padx=12, pady=(6, 4))
        left = tk.Frame(self.cur_frame, bg=T["card"])
        left.pack(side="left", fill="y")
        self.city_lbl = self._lbl(left, size=14, bold=True)
        self.city_lbl.pack(anchor="w")
        row = tk.Frame(left, bg=T["card"])
        row.pack(anchor="w", pady=(2, 0))
        self.icon_lbl = self._lbl(row, size=40)
        self.icon_lbl.pack(side="left")
        self.temp_lbl = self._lbl(row, size=40, bold=True)
        self.temp_lbl.pack(side="left", padx=(8, 0))
        self.desc_lbl = self._lbl(left, size=11, color=T["muted"])
        self.desc_lbl.pack(anchor="w")
        self.moon_lbl = self._lbl(left, size=10, color=T["muted"])
        self.moon_lbl.pack(anchor="w", pady=(8, 0))
        self.day_lbl = self._lbl(left, size=10, color=T["muted"])
        self.day_lbl.pack(anchor="w")

        right = tk.Frame(self.cur_frame, bg=T["card"])
        right.pack(side="right", fill="y")
        self.details = {}
        keys = ["Odczuwalna", "Wilgotność", "Wiatr", "Porywy", "Ciśnienie", "Opad",
                "Zachmurzenie", "Widzialność", "Indeks UV", "Jakość powietrza", "PM2.5 / PM10",
                "Wschód / zachód"]
        for i, key in enumerate(keys):
            col, r = divmod(i, 6)
            self._lbl(right, key + ":", color=T["muted"]).grid(row=r, column=col * 2, sticky="w",
                                                               padx=(18 if col else 0, 6))
            v = self._lbl(right, bold=True)
            v.grid(row=r, column=col * 2 + 1, sticky="e")
            self.details[key] = v

        # --- wykres 48 h
        chart_card = ttk.Frame(self, style="Card.TFrame", padding=(10, 6, 10, 6))
        chart_card.pack(fill="x", padx=12, pady=4)
        self.chart_title = self._lbl(chart_card, "Najbliższe 48 godzin", bold=True)
        self.chart_title.pack(anchor="w")
        self.chart = tk.Canvas(chart_card, height=175, bg=T["card"], highlightthickness=0)
        self.chart.pack(fill="x")
        self.chart.bind("<Configure>", lambda e: self.draw_chart())

        # --- 7 dni
        self.days_frame = ttk.Frame(self, padding=(12, 4, 12, 4))
        self.days_frame.pack(fill="both", expand=True)

        # --- status
        self.status = tk.Label(self, text="", fg=T["muted"], bg=T["bg"],
                               font=("Segoe UI", 9), anchor="w")
        self.status.pack(fill="x", padx=12, pady=(0, 8))
        self._render_favs()

    # ======================================================== wątki
    def _poll(self):
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _post(self, fn):
        self._q.put(fn)

    def _bg(self, fn, callback):
        def worker():
            try:
                res, err = fn(), None
            except Exception as e:
                res, err = None, e
            self._post(lambda: callback(res, err))
        threading.Thread(target=worker, daemon=True).start()

    def set_status(self, text, warn=False):
        if self.status.winfo_exists():
            self.status.config(text=text, fg=self.T["warn"] if warn else self.T["muted"])

    # ======================================================== miasta
    def do_search(self):
        q = self.search_var.get().strip()
        if not q:
            return
        self.set_status(f"Szukam „{q}”…")
        self._bg(lambda: search_cities(q), self._on_search_done)

    def _on_search_done(self, results, err):
        if err:
            self.set_status(f"Błąd wyszukiwania: {err}", warn=True)
            return
        self.results = results
        if not results:
            self.combo["values"] = []
            self.combo.set("Nie znaleziono miasta")
            self.set_status("Brak wyników")
            return
        self.combo["values"] = [city_label(c) for c in results]
        self.combo.current(0)
        self.set_status(f"Znaleziono {len(results)} – wybierz z listy")
        if len(results) == 1:
            self.on_city_selected()
        else:
            self.combo.event_generate("<Button-1>")

    def on_city_selected(self, _=None):
        i = self.combo.current()
        if 0 <= i < len(self.results):
            c = self.results[i]
            self.set_city({k: c.get(k) for k in ("name", "admin1", "country", "latitude", "longitude")})

    def set_city(self, city):
        self.city = city
        self.cfg["city"] = city
        save_json(CONFIG_FILE, self.cfg)
        self._render_favs()
        self.load_weather()

    def locate_by_ip(self, first_run=False):
        self.set_status("Ustalam lokalizację na podstawie adresu IP…")

        def done(city, err):
            if err:
                self.set_status(f"Lokalizacja IP: {err}", warn=True)
                if first_run or not self.city:
                    self.set_city(DEFAULT_CITY)
                return
            self.set_city(city)
        self._bg(ip_locate, done)

    # ======================================================== ulubione
    def _render_favs(self):
        if not self.fav_frame.winfo_exists():
            return
        for w in self.fav_frame.winfo_children():
            w.destroy()
        is_fav = any(same_city(f, self.city) for f in self.cfg["favorites"])
        ttk.Button(self.fav_frame, text="★ Ulubione" if is_fav else "☆ Dodaj do ulubionych",
                   style="Fav.TButton", command=self.toggle_fav).pack(side="left")
        for fav in self.cfg["favorites"][:8]:
            b = ttk.Button(self.fav_frame, text=fav["name"], style="Fav.TButton",
                           command=lambda f=fav: self.set_city(dict(f)))
            b.pack(side="left", padx=(6, 0))
            b.bind("<Button-3>", lambda e, f=fav: self.remove_fav(f))
        if self.cfg["favorites"]:
            tk.Label(self.fav_frame, text="(PPM – usuń)", fg=self.T["muted"], bg=self.T["bg"],
                     font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))

    def toggle_fav(self):
        if not self.city:
            return
        favs = self.cfg["favorites"]
        if any(same_city(f, self.city) for f in favs):
            self.cfg["favorites"] = [f for f in favs if not same_city(f, self.city)]
        else:
            favs.append(dict(self.city))
        save_json(CONFIG_FILE, self.cfg)
        self._render_favs()

    def remove_fav(self, fav):
        if messagebox.askyesno(APP_NAME, f"Usunąć „{fav['name']}” z ulubionych?", parent=self):
            self.cfg["favorites"] = [f for f in self.cfg["favorites"] if not same_city(f, fav)]
            save_json(CONFIG_FILE, self.cfg)
            self._render_favs()

    # ======================================================== pobieranie
    def _cache_key(self):
        c = self.city
        return f"{c['latitude']:.3f},{c['longitude']:.3f},{self.cfg['temp_unit']},{self.cfg['wind_unit']}"

    def load_weather(self):
        if not self.city:
            return
        if self.refresh_job:
            self.after_cancel(self.refresh_job)
        self.refresh_job = self.after(max(5, int(self.cfg["refresh_min"])) * 60000, self.load_weather)
        self.set_status("Pobieram prognozę…")
        c, cfg = dict(self.city), dict(self.cfg)

        def fetch():
            fc = get_forecast(c["latitude"], c["longitude"], cfg)
            try:
                air = get_air(c["latitude"], c["longitude"])
            except Exception:
                air = None
            return fc, air
        self._bg(fetch, self._on_weather)

    def _on_weather(self, res, err):
        key = self._cache_key()
        if err:
            cache = load_json(CACHE_FILE, {}).get(key)
            if not cache:
                self.set_status(f"Błąd pobierania: {err} – brak danych w pamięci podręcznej", warn=True)
                return
            self.data, self.air = cache["forecast"], cache.get("air")
            self.offline_ts = cache["ts"]
        else:
            self.data, self.air = res
            self.offline_ts = None
            cache = load_json(CACHE_FILE, {})
            cache[key] = {"ts": datetime.now().isoformat(timespec="seconds"),
                          "forecast": self.data, "air": self.air}
            if len(cache) > 20:  # nie rozrastaj pliku w nieskończoność
                for k in sorted(cache, key=lambda k: cache[k]["ts"])[:-20]:
                    cache.pop(k)
            save_json(CACHE_FILE, cache)
        self.render()
        if not self.offline_ts:
            self.check_alerts()

    # ======================================================== renderowanie
    def _hour_index(self):
        hr = self.data["hourly"]["time"]
        key = self.data["current"]["time"][:13] + ":00"
        if key in hr:
            return hr.index(key)
        for i, t in enumerate(hr):
            if t >= key:
                return i
        return 0

    def render(self):
        if not self.data or not self.city_lbl.winfo_exists():
            return
        T, d = self.T, self.data
        cur, daily, hourly = d["current"], d["daily"], d["hourly"]
        tu, wu = TEMP_UNITS[self.cfg["temp_unit"]][1], WIND_UNITS[self.cfg["wind_unit"]]
        code = cur["weather_code"]
        desc, icon = WMO.get(code, ("—", "❔"))
        if not cur.get("is_day", 1):
            icon = NIGHT_ICONS.get(code, icon)

        self.title(f"{APP_NAME} – {self.city['name']}")
        self.city_lbl.config(text=city_label(self.city))
        self.icon_lbl.config(text=icon)
        self.temp_lbl.config(text=f"{cur['temperature_2m']:.0f}{tu}")
        self.desc_lbl.config(text=desc)

        today = cur["time"][:10]
        di = daily["time"].index(today) if today in daily["time"] else 0
        name, micon, illum = moon_phase(datetime.now())
        self.moon_lbl.config(text=f"{micon} {name} ({illum}% oświetlenia)")
        dl = daily["daylight_duration"][di] or 0
        self.day_lbl.config(text=f"☀ Długość dnia: {int(dl // 3600)} h {int(dl % 3600 // 60)} min")

        # trend ciśnienia (3 h)
        hi = self._hour_index()
        p_now = cur["pressure_msl"]
        trend = ""
        if hi >= 3 and hourly["pressure_msl"][hi - 3] is not None:
            diff = p_now - hourly["pressure_msl"][hi - 3]
            arrow = "↗" if diff > 1 else "↘" if diff < -1 else "→"
            trend = f" {arrow} {diff:+.1f}/3h"

        wd = KIERUNKI[round((cur["wind_direction_10m"] or 0) / 45) % 8]
        vis = cur.get("visibility")
        det = self.details
        det["Odczuwalna"].config(text=f"{cur['apparent_temperature']:.0f}{tu}")
        det["Wilgotność"].config(text=f"{cur['relative_humidity_2m']}%")
        det["Wiatr"].config(text=f"{cur['wind_speed_10m']:.0f} {wu} {wd}")
        det["Porywy"].config(text=f"{cur['wind_gusts_10m']:.0f} {wu}")
        det["Ciśnienie"].config(text=f"{p_now:.0f} hPa{trend}")
        det["Opad"].config(text=f"{cur['precipitation']:.1f} mm")
        det["Zachmurzenie"].config(text=f"{cur['cloud_cover']}%")
        det["Widzialność"].config(text=f"{vis / 1000:.1f} km" if vis is not None else "–")
        det["Indeks UV"].config(text=uv_label(cur.get("uv_index")))
        ac = (self.air or {}).get("current", {})
        det["Jakość powietrza"].config(text=aqi_label(ac.get("european_aqi")))
        pm25, pm10 = ac.get("pm2_5"), ac.get("pm10")
        det["PM2.5 / PM10"].config(text=f"{pm25:.0f} / {pm10:.0f} µg/m³" if pm25 is not None
                                   and pm10 is not None else "–")
        det["Wschód / zachód"].config(text=f"{daily['sunrise'][di][-5:]} / {daily['sunset'][di][-5:]}")

        # 7 dni
        for w in self.days_frame.winfo_children():
            w.destroy()
        for col, i in enumerate(range(di, min(di + 7, len(daily["time"])))):
            dt = datetime.strptime(daily["time"][i], "%Y-%m-%d")
            ddesc, dicon = WMO.get(daily["weather_code"][i], ("—", "❔"))
            card = tk.Frame(self.days_frame, bg=T["card"], padx=4, pady=8)
            card.grid(row=0, column=col, sticky="nsew", padx=3)
            self.days_frame.columnconfigure(col, weight=1, uniform="d")
            self.days_frame.rowconfigure(0, weight=1)
            self._lbl(card, "Dziś" if col == 0 else DNI[dt.weekday()], 11, True).pack()
            self._lbl(card, dt.strftime("%d.%m"), 9, color=T["muted"]).pack()
            self._lbl(card, dicon, 22).pack(pady=2)
            self._lbl(card, f"{daily['temperature_2m_max'][i]:.0f}°", 12, True).pack()
            self._lbl(card, f"{daily['temperature_2m_min'][i]:.0f}°", 10, color=T["muted"]).pack()
            prob, psum = daily["precipitation_probability_max"][i], daily["precipitation_sum"][i]
            self._lbl(card, f"💧 {prob if prob is not None else '–'}%  {psum or 0:.1f} mm", 9,
                      color=T["accent"]).pack(pady=(3, 0))
            g = daily["wind_gusts_10m_max"][i]
            self._lbl(card, f"💨 {g:.0f} {wu}" if g is not None else "", 9, color=T["muted"]).pack()
            self._lbl(card, ddesc, 8, color=T["muted"], wraplength=95).pack(pady=(3, 0))

        self.draw_chart()
        self._render_widget()
        self._update_tray()

        if self.offline_ts:
            ts = datetime.fromisoformat(self.offline_ts)
            self.set_status(f"⚠ Brak połączenia – dane z {ts:%d.%m %H:%M} (nieaktualne)", warn=True)
        else:
            self.set_status(f"Zaktualizowano {datetime.now():%H:%M:%S} · dane: Open-Meteo · "
                            f"odświeżanie co {self.cfg['refresh_min']} min")

    def draw_chart(self):
        c = self.chart
        if not c.winfo_exists():
            return
        c.delete("all")
        if not self.data:
            return
        T = self.T
        w, h = c.winfo_width(), c.winfo_height()
        if w < 100:
            return
        hr = self.data["hourly"]
        i0 = self._hour_index()
        sl = slice(i0, i0 + 48)
        times = hr["time"][sl]
        temps = [t if t is not None else 0 for t in hr["temperature_2m"][sl]]
        prec = [p or 0 for p in hr["precipitation"][sl]]
        codes = hr["weather_code"][sl]
        days = hr["is_day"][sl]
        n = len(temps)
        if n < 2:
            return
        pl, pr, pt, pb = 40, 12, 40, 22
        pw, ph = w - pl - pr, h - pt - pb
        tmin, tmax = min(temps), max(temps)
        if tmax - tmin < 4:
            mid = (tmax + tmin) / 2
            tmin, tmax = mid - 2, mid + 2
        pmax = max(max(prec), 3)
        step = pw / (n - 1)
        X = lambda i: pl + i * step
        Y = lambda t: pt + (tmax - t) / (tmax - tmin) * ph

        # siatka i oś Y
        for k in range(3):
            t = tmin + (tmax - tmin) * k / 2
            y = Y(t)
            c.create_line(pl, y, w - pr, y, fill=T["grid"], dash=(2, 4))
            c.create_text(pl - 6, y, text=f"{t:.0f}°", anchor="e", fill=T["muted"], font=("Segoe UI", 8))
        # opady
        bw = max(step * 0.7, 2)
        for i, p in enumerate(prec):
            if p > 0:
                bh = p / pmax * ph * 0.45
                c.create_rectangle(X(i) - bw / 2, pt + ph - bh, X(i) + bw / 2, pt + ph,
                                   fill=T["rain"], outline="")
        # północ + etykiety godzin
        for i, t in enumerate(times):
            hh = int(t[11:13])
            if hh == 0 and i > 0:
                c.create_line(X(i), 2, X(i), pt + ph, fill=T["muted"], dash=(4, 3))
                dt = datetime.strptime(t[:10], "%Y-%m-%d")
                c.create_text(X(i) + 5, 8, text=f"{DNI[dt.weekday()]} {dt:%d.%m}", anchor="w",
                              fill=T["muted"], font=("Segoe UI", 8, "bold"))
            if hh % 3 == 0:
                c.create_text(X(i), h - 8, text=f"{hh:02d}", fill=T["muted"], font=("Segoe UI", 8))
        # linia temperatury
        pts = []
        for i, t in enumerate(temps):
            pts += [X(i), Y(t)]
        c.create_line(*pts, fill=T["accent"], width=2.5, smooth=True)
        for i in range(2, n, 6):
            ic = WMO.get(codes[i], ("", ""))[1]
            if not days[i]:
                ic = NIGHT_ICONS.get(codes[i], ic)
            c.create_text(X(i), Y(temps[i]) - 12, text=f"{temps[i]:.0f}°", fill=T["fg"],
                          font=("Segoe UI", 8, "bold"))
            c.create_text(X(i), pt - 14, text=ic, fill=T["fg"], font=("Segoe UI Emoji", 10))
        self.chart_title.config(text=f"Najbliższe 48 godzin  ·  linia: temperatura  ·  "
                                     f"słupki: opad (skala do {pmax:.1f} mm/h)")

    # ======================================================== ostrzeżenia
    def check_alerts(self):
        a = self.cfg["alerts"]
        alerts = []
        if a["enabled"] and self.data:
            hr = self.data["hourly"]
            i0 = self._hour_index()
            sl = slice(i0, i0 + 24)
            times = hr["time"][sl]
            to_c = (lambda t: (t - 32) * 5 / 9) if self.cfg["temp_unit"] == "F" else (lambda t: t)
            k = WIND_TO_KMH[self.cfg["wind_unit"]]
            if a["storm"]:
                for t, code in zip(times, hr["weather_code"][sl]):
                    if code in STORM_CODES:
                        alerts.append(("storm", f"⛈ Burza prognozowana ok. {t[11:16]}"))
                        break
            gusts = [g * k for g in hr["wind_gusts_10m"][sl] if g is not None]
            if gusts and max(gusts) >= a["gust"]:
                alerts.append(("gust", f"💨 Porywy wiatru do {max(gusts):.0f} km/h"))
            temps = [to_c(t) for t in hr["temperature_2m"][sl] if t is not None]
            if temps and min(temps) <= a["frost"]:
                alerts.append(("frost", f"🥶 Spadek temperatury do {min(temps):.0f}°C"))
            rain = sum(p or 0 for p in hr["precipitation"][sl])
            if rain >= a["rain"]:
                alerts.append(("rain", f"🌧 Duży opad: {rain:.0f} mm w ciągu 24 h"))
        self.active_alerts = alerts
        if alerts:
            self.alert_lbl.config(text="Ostrzeżenia (24 h):  " + "   ·   ".join(t for _, t in alerts))
            self.alert_lbl.pack(fill="x", padx=12, pady=(4, 0), after=self.fav_frame)
        else:
            self.alert_lbl.pack_forget()
        new = []
        for kind, text in alerts:
            key = (self.city["name"], kind, datetime.now().strftime("%Y-%m-%d"))
            if key not in self.notified:
                self.notified.add(key)
                new.append(text)
        if new:
            self.notify(f"{APP_NAME} – {self.city['name']}", "\n".join(new))

    def notify(self, title, msg):
        if self.tray:
            try:
                self.tray.notify(msg, title)
                return
            except Exception:
                pass
        self._toast(title, msg)

    def _toast(self, title, msg):
        T = self.T
        t = tk.Toplevel(self)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=T["card"], padx=14, pady=10, highlightthickness=1,
                    highlightbackground=T["warn"])
        self._lbl(t, title, 10, True, color=T["warn"]).pack(anchor="w")
        self._lbl(t, msg, 10, justify="left").pack(anchor="w")
        t.update_idletasks()
        x = t.winfo_screenwidth() - t.winfo_width() - 20
        y = t.winfo_screenheight() - t.winfo_height() - 60
        t.geometry(f"+{x}+{y}")
        t.bind("<Button-1>", lambda e: t.destroy())
        t.after(10000, lambda: t.winfo_exists() and t.destroy())

    # ======================================================== zasobnik
    def _tray_image(self, text):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        dr.rounded_rectangle((0, 0, 63, 63), radius=14, fill=(31, 111, 209, 255))
        font = None
        for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(name, 30 if len(text) <= 3 else 24)
                break
            except Exception:
                pass
        font = font or ImageFont.load_default()
        bbox = dr.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        dr.text(((64 - tw) / 2 - bbox[0], (64 - th) / 2 - bbox[1]), text, font=font, fill="white")
        return img

    def _start_tray(self):
        if not HAS_TRAY:
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Pokaż okno", lambda: self._post(self.show_window), default=True),
                pystray.MenuItem("Tryb widżetu", lambda: self._post(self.toggle_widget)),
                pystray.MenuItem("Odśwież", lambda: self._post(self.load_weather)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Zakończ", lambda: self._post(self.quit_app)),
            )
            self.tray = pystray.Icon("pogoda", self._tray_image("…"), APP_NAME, menu)
            self.tray.run_detached()
        except Exception:
            self.tray = None

    def _update_tray(self):
        if not (self.tray and self.data):
            return
        try:
            cur = self.data["current"]
            t = f"{cur['temperature_2m']:.0f}°"
            self.tray.icon = self._tray_image(t)
            desc = WMO.get(cur["weather_code"], ("", ""))[0]
            self.tray.title = f"{self.city['name']}: {t}{self.cfg['temp_unit']}, {desc}"[:127]
        except Exception:
            pass

    def show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def on_close(self):
        if self.cfg["minimize_to_tray"] and self.tray:
            self.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.notify(APP_NAME, "Aplikacja działa dalej w zasobniku systemowym.")
        else:
            self.quit_app()

    def quit_app(self):
        if self.widget and self.widget.winfo_exists():
            self._save_widget_pos()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.destroy()

    # ======================================================== widżet
    def toggle_widget(self):
        if self.widget and self.widget.winfo_exists():
            self.close_widget()
        else:
            self.open_widget()

    def open_widget(self):
        T = self.T
        w = tk.Toplevel(self)
        self.widget = w
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        try:
            w.attributes("-alpha", 0.94)
        except tk.TclError:
            pass
        w.configure(bg=T["card"], padx=12, pady=8, highlightthickness=1,
                    highlightbackground=T["grid"])
        row = tk.Frame(w, bg=T["card"])
        row.pack(anchor="w")
        self.w_icon = self._lbl(row, size=24)
        self.w_icon.pack(side="left")
        self.w_temp = self._lbl(row, size=24, bold=True)
        self.w_temp.pack(side="left", padx=(6, 0))
        self.w_city = self._lbl(w, size=10, bold=True)
        self.w_city.pack(anchor="w")
        self.w_desc = self._lbl(w, size=9, color=T["muted"])
        self.w_desc.pack(anchor="w")

        menu = tk.Menu(w, tearoff=0)
        menu.add_command(label="Pokaż okno", command=lambda: self.close_widget())
        menu.add_command(label="Odśwież", command=self.load_weather)
        menu.add_separator()
        menu.add_command(label="Zakończ", command=self.quit_app)

        def press(e):
            w._dx, w._dy = e.x_root - w.winfo_x(), e.y_root - w.winfo_y()

        def drag(e):
            w.geometry(f"+{e.x_root - w._dx}+{e.y_root - w._dy}")

        for el in [w, row, self.w_icon, self.w_temp, self.w_city, self.w_desc]:
            el.bind("<ButtonPress-1>", press)
            el.bind("<B1-Motion>", drag)
            el.bind("<ButtonRelease-1>", lambda e: self._save_widget_pos())
            el.bind("<Double-Button-1>", lambda e: self.close_widget())
            el.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        self._render_widget()
        w.update_idletasks()
        pos = self.cfg.get("widget_pos")
        if pos:
            x, y = pos
        else:
            x = w.winfo_screenwidth() - w.winfo_width() - 30
            y = w.winfo_screenheight() - w.winfo_height() - 80
        w.geometry(f"+{x}+{y}")
        self.withdraw()

    def _render_widget(self):
        if not (self.widget and self.widget.winfo_exists() and self.data):
            return
        cur = self.data["current"]
        desc, icon = WMO.get(cur["weather_code"], ("—", "❔"))
        if not cur.get("is_day", 1):
            icon = NIGHT_ICONS.get(cur["weather_code"], icon)
        self.w_icon.config(text=icon)
        self.w_temp.config(text=f"{cur['temperature_2m']:.0f}{TEMP_UNITS[self.cfg['temp_unit']][1]}")
        self.w_city.config(text=self.city["name"])
        warn = f" · ⚠ {len(self.active_alerts)}" if self.active_alerts else ""
        self.w_desc.config(text=desc + warn)

    def _save_widget_pos(self):
        if self.widget and self.widget.winfo_exists():
            self.cfg["widget_pos"] = [self.widget.winfo_x(), self.widget.winfo_y()]
            save_json(CONFIG_FILE, self.cfg)

    def close_widget(self, show_main=True):
        if self.widget and self.widget.winfo_exists():
            self._save_widget_pos()
            self.widget.destroy()
        self.widget = None
        if show_main:
            self.show_window()

    # ======================================================== ustawienia
    def show_settings(self):
        T, cfg = self.T, self.cfg
        win = tk.Toplevel(self)
        win.title("Ustawienia")
        win.configure(bg=T["card"], padx=16, pady=14)
        win.resizable(False, False)
        win.transient(self)

        v_temp = tk.StringVar(value=cfg["temp_unit"])
        v_wind = tk.StringVar(value=WIND_UNITS[cfg["wind_unit"]])
        v_theme = tk.StringVar(value=THEME_NAMES[cfg["theme"]])
        v_refresh = tk.IntVar(value=cfg["refresh_min"])
        v_tray = tk.BooleanVar(value=cfg["minimize_to_tray"])
        v_auto = tk.BooleanVar(value=get_autostart())
        a = cfg["alerts"]
        v_al = tk.BooleanVar(value=a["enabled"])
        v_storm = tk.BooleanVar(value=a["storm"])
        v_gust = tk.IntVar(value=a["gust"])
        v_frost = tk.IntVar(value=a["frost"])
        v_rain = tk.IntVar(value=a["rain"])

        def section(title):
            f = ttk.LabelFrame(win, text=title, padding=10)
            f.pack(fill="x", pady=(0, 10))
            return f

        f = section("Jednostki")
        ttk.Label(f, text="Temperatura:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(f, text="°C", value="C", variable=v_temp).grid(row=0, column=1, padx=6)
        ttk.Radiobutton(f, text="°F", value="F", variable=v_temp).grid(row=0, column=2)
        ttk.Label(f, text="Wiatr:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(f, textvariable=v_wind, values=list(WIND_UNITS.values()), state="readonly",
                     width=8).grid(row=1, column=1, columnspan=2, sticky="w", padx=6, pady=(6, 0))

        f = section("Wygląd i działanie")
        ttk.Label(f, text="Motyw:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(f, textvariable=v_theme, values=list(THEME_NAMES.values()), state="readonly",
                     width=12).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(f, text="Odświeżanie co (min):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(f, from_=5, to=180, increment=5, textvariable=v_refresh, width=6).grid(
            row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        cb = ttk.Checkbutton(f, text="Zamykanie okna minimalizuje do zasobnika", variable=v_tray)
        cb.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        if not HAS_TRAY:
            cb.state(["disabled"])
            ttk.Label(f, text="(wymaga: pip install pystray pillow)", foreground=T["muted"]).grid(
                row=3, column=0, columnspan=2, sticky="w")
        cb2 = ttk.Checkbutton(f, text="Uruchamiaj razem z Windows", variable=v_auto)
        cb2.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        if not winreg:
            cb2.state(["disabled"])

        f = section("Ostrzeżenia (najbliższe 24 h)")
        ttk.Checkbutton(f, text="Włącz ostrzeżenia i powiadomienia", variable=v_al).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(f, text="Burze", variable=v_storm).grid(row=1, column=0, columnspan=2,
                                                                sticky="w", pady=(4, 0))
        for r, (txt, var, lo, hi) in enumerate([("Porywy wiatru od (km/h):", v_gust, 20, 200),
                                                ("Temperatura poniżej (°C):", v_frost, -40, 20),
                                                ("Suma opadu od (mm):", v_rain, 1, 200)], start=2):
            ttk.Label(f, text=txt).grid(row=r, column=0, sticky="w", pady=(4, 0))
            ttk.Spinbox(f, from_=lo, to=hi, textvariable=var, width=6).grid(
                row=r, column=1, sticky="w", padx=6, pady=(4, 0))

        def save():
            try:
                old = (cfg["temp_unit"], cfg["wind_unit"], cfg["theme"], cfg["refresh_min"])
                cfg["temp_unit"] = v_temp.get()
                cfg["wind_unit"] = {v: k for k, v in WIND_UNITS.items()}[v_wind.get()]
                cfg["theme"] = {v: k for k, v in THEME_NAMES.items()}[v_theme.get()]
                cfg["refresh_min"] = max(5, int(v_refresh.get()))
                cfg["minimize_to_tray"] = v_tray.get()
                cfg["alerts"] = {"enabled": v_al.get(), "storm": v_storm.get(),
                                 "gust": int(v_gust.get()), "frost": int(v_frost.get()),
                                 "rain": int(v_rain.get())}
            except (tk.TclError, ValueError):
                messagebox.showerror(APP_NAME, "Nieprawidłowa wartość liczbowa.", parent=win)
                return
            save_json(CONFIG_FILE, cfg)
            try:
                if v_auto.get() != get_autostart():
                    set_autostart(v_auto.get())
            except OSError as e:
                messagebox.showwarning(APP_NAME, f"Nie udało się zmienić autostartu: {e}", parent=win)
            win.destroy()
            self.notified.clear()
            if cfg["theme"] != old[2]:
                self._apply_theme()
            if (cfg["temp_unit"], cfg["wind_unit"], cfg["refresh_min"]) != (old[0], old[1], old[3]):
                self.load_weather()
            else:
                self.check_alerts()

        btns = tk.Frame(win, bg=T["card"])
        btns.pack(fill="x")
        ttk.Button(btns, text="Anuluj", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Zapisz", command=save).pack(side="right", padx=(0, 6))
        win.bind("<Escape>", lambda e: win.destroy())
        self._center(win)
        win.grab_set()

    # ======================================================== o aplikacji
    def show_about(self):
        if getattr(self, "_about", None) and self._about.winfo_exists():
            self._about.lift()
            return
        T = self.T
        win = tk.Toplevel(self)
        self._about = win
        win.title(f"O aplikacji {APP_NAME}")
        win.configure(bg=T["card"], padx=28, pady=20)
        win.resizable(False, False)
        win.transient(self)

        def lbl(text, size=10, bold=False, color=None, pady=0):
            l = self._lbl(win, text, size, bold, color=color, justify="center")
            l.pack(pady=pady)
            return l

        def link(text, url):
            l = lbl(text, color=T["accent"])
            l.configure(cursor="hand2", font=("Segoe UI", 10, "underline"))
            l.bind("<Button-1>", lambda e: webbrowser.open(url))

        lbl("⛅", 40)
        lbl(APP_NAME, 18, True)
        lbl(f"Wersja {APP_VERSION}", 9, color=T["muted"], pady=(0, 10))
        lbl("Okienkowa prognoza pogody z wyborem miasta,\nwykresem 48 h, ostrzeżeniami i widżetem.", 10)
        lbl("Autor", 9, color=T["muted"], pady=(14, 0))
        lbl(AUTHOR, 12, True)
        link(AUTHOR_EMAIL, f"mailto:{AUTHOR_EMAIL}")
        link(AUTHOR_GITHUB.replace("https://", ""), AUTHOR_GITHUB)
        lbl("Projekt", 9, color=T["muted"], pady=(14, 0))
        link(PROJECT_URL.replace("https://", ""), PROJECT_URL)
        lbl("Dane pogodowe i jakość powietrza", 9, color=T["muted"], pady=(14, 0))
        link("Open-Meteo.com (CC BY 4.0)", "https://open-meteo.com")
        lbl(f"© {datetime.now().year} {AUTHOR} · licencja MIT", 9, color=T["muted"], pady=(14, 8))
        ttk.Button(win, text="Zamknij", command=win.destroy).pack()
        win.bind("<Escape>", lambda e: win.destroy())
        self._center(win)
        win.grab_set()
        win.focus_set()

    def _center(self, win):
        win.update_idletasks()
        if self.state() == "withdrawn":
            x = (win.winfo_screenwidth() - win.winfo_width()) // 2
            y = (win.winfo_screenheight() - win.winfo_height()) // 2
        else:
            x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def main():
    if sys.platform == "win32":
        try:  # ostre czcionki na ekranach HiDPI
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = WeatherApp(start_minimized="--minimized" in sys.argv)
    app.mainloop()
    if app.tray:
        try:
            app.tray.stop()
        except Exception:
            pass
    os._exit(0)  # nie czekaj na wątki tła (pobieranie, zasobnik)


if __name__ == "__main__":
    main()
