import os
import pandas as pd
import numpy as np
import duckdb
import folium
import subprocess
import uuid
from functools import wraps

from flask import Flask, render_template, request, flash, redirect, url_for, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from task_manager import TaskManager, enqueue_data_processing_task, get_queue_status
from models import TaskStatus
from llm_cache import get_cache_stats, clear_cache
from ml_worker_filter import get_ml_filter, train_ml_filter_from_llm_log
from connection_pool import get_connection_pool_stats
from incremental_processing import get_incremental_processor

# Importáld a legfrissebb kerülethatárokat generált Python fájlból
import sys
import os as _os
sys.path.append(_os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..')))
import json

# --- Konfiguráció ---
# A Docker konténeren belüli abszolút elérési utakat használjuk.
WORKSPACE_DIR = '/workspace'
APP_DIR = os.path.join(WORKSPACE_DIR, 'app')
STATIC_DIR = os.path.join(APP_DIR, 'static')
PARQUET_DIR = os.path.join(WORKSPACE_DIR, 'parquet')
RELEVANT_FILE = os.path.join(PARQUET_DIR, 'core_layer_filtered.parquet')
IRRELEVANT_FILE = os.path.join(PARQUET_DIR, 'core_layer_irrelevant.parquet')
MAP_OUTPUT_FILE = os.path.join(STATIC_DIR, 'map_render.html')

app = Flask(__name__, template_folder=APP_DIR)
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')  # Alapértelmezett jelszó fejlesztéshez

# WebSocket támogatás real-time progress tracking-hez
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Admin védelem dekorátor ---
def admin_required(f):
    """Ellenőrzi, hogy a felhasználó be van-e jelentkezve admin-ként."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Ehhez a funkcióhoz admin jogosultság szükséges!', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Task manager inicializálása SocketIO-val
task_manager = TaskManager(socketio)

# --- Segédfüggvények ---
def get_data(file_path):
    """Biztonságosan betölt egy Parquet fájlt, vagy üres DataFrame-et ad vissza."""
    if os.path.exists(file_path):
        try:
            return pd.read_parquet(file_path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

# --- Útvonalak (Routes) ---

@app.route('/')
def index():
    """A főoldal, ahonnan a feldolgozást lehet indítani."""
    return render_template('index.html')

# --- Admin Login / Logout ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Admin bejelentkezési oldal."""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
            flash('Sikeres bejelentkezés!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Hibás jelszó!', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Admin kijelentkezés."""
    session.pop('logged_in', None)
    flash('Sikeresen kijelentkeztél.', 'info')
    return redirect(url_for('index'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin vezérlőpult - csak bejelentkezve elérhető."""
    return render_template('admin.html')

@app.route('/run-pipeline', methods=['POST'])
@admin_required
def run_pipeline():
    """Elindítja az adatfeldolgozást aszinkron módon RQ háttérfeladatként."""
    try:
        # Új feladat létrehozása
        task_id = task_manager.create_task()
        
        # Feladat beütemezése a háttérben (normál mód: test_mode=False)
        job_id = enqueue_data_processing_task(task_id, test_mode=False)
        
        # Sikeres válasz a task_id-val
        return jsonify({
            'success': True, 
            'task_id': task_id,
            'message': 'Az adatfeldolgozás elindult a háttérben. A haladás követhető a /task-status API-n.'
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': str(e),
            'message': f'Hiba történt a folyamat indításakor: {e}'
        }), 500

@app.route('/run-pipeline-test', methods=['POST'])
@admin_required
def run_pipeline_test():
    """Teszt feldolgozás: első 100 cikk worker + első 50 LLM elemzés."""
    try:
        # Új feladat létrehozása
        task_id = task_manager.create_task()
        
        # Feladat beütemezése TESZT MÓDBAN (test_mode=True)
        job_id = enqueue_data_processing_task(task_id, test_mode=True)
        
        # Sikeres válasz a task_id-val
        return jsonify({
            'success': True, 
            'task_id': task_id,
            'message': f'🧪 TESZT feldolgozás elindult: első 100 cikk worker + első 50 LLM elemzés'
        })
        
    except Exception as e:
        return jsonify({
            'success': False, 
            'error': str(e),
            'message': f'Hiba történt a folyamat indításakor: {e}'
        }), 500

@app.route('/task-status/<task_id>')
def get_task_status(task_id: str):
    """Feladat státusz lekérdezése API végpont."""
    status = task_manager.get_status(task_id)
    if not status:
        return jsonify({'success': False, 'error': 'Feladat nem található'}), 404
    
    return jsonify({
        'success': True,
        'status': status.model_dump()
    })

@app.route('/queue-status')
def get_queue_status_endpoint():
    """RQ queue státusz információk."""
    try:
        queue_info = get_queue_status()
        return jsonify(queue_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# WebSocket események real-time frissítésekhez
@socketio.on('subscribe_to_task')
def handle_task_subscription(data):
    """Kliens feliratkozása egy feladat státusz frissítéseire."""
    task_id = data.get('task_id')
    if task_id:
        # Kliens hozzáadása a task-specifikus room-hoz
        join_room(task_id)
        emit('subscribed', {'task_id': task_id})
        
        # Aktuális státusz küldése
        status = task_manager.get_status(task_id)
        if status:
            emit('status_update', status.model_dump())

@socketio.on('unsubscribe_from_task')
def handle_task_unsubscription(data):
    """Kliens leiratkozása feladat frissítéseiről."""
    task_id = data.get('task_id')
    if task_id:
        leave_room(task_id)
        emit('unsubscribed', {'task_id': task_id})

@app.route('/stats')
def stats():
    """Továbbfejlesztett statisztikai oldal queue információkkal."""
    relevant_df = get_data(RELEVANT_FILE)
    irrelevant_df = get_data(IRRELEVANT_FILE)
    
    # Queue státusz hozzáadása
    try:
        queue_info = get_queue_status()
    except:
        queue_info = {'error': 'Queue információ nem elérhető'}
    
    stats_data = {
        'relevant_count': len(relevant_df),
        'irrelevant_count': len(irrelevant_df),
        'total_count': len(relevant_df) + len(irrelevant_df),
        'queue_info': queue_info
    }
    return render_template('stats.html', stats=stats_data)

@app.route('/data')
def data_table():
    """Megjeleníti a releváns adatokat egy táblázatban."""
    """Megjeleníti a releváns és irreleváns adatokat egy táblázatban."""
    relevant_df = get_data(RELEVANT_FILE)
    irrelevant_df = get_data(IRRELEVANT_FILE)

    tables = []

    # Releváns adatok
    html_chunk = "<h3>Releváns hirdetések</h3>"
    if not relevant_df.empty:
        df_copy = relevant_df.copy()
        if 'description' in df_copy.columns:
            df_copy['description_short'] = df_copy['description'].astype(str).str.slice(0, 150) + '...'
        html_chunk += df_copy.to_html(classes='data table table-striped', header="true", index=False, escape=False)
    else:
        html_chunk += "<p>Nincsenek releváns adatok.</p>"
    tables.append(html_chunk)

    # Nem releváns adatok
    html_chunk = "<h3>Nem releváns hirdetések</h3>"
    if not irrelevant_df.empty:
        df_copy = irrelevant_df.copy()
        if 'description' in df_copy.columns:
            df_copy['description_short'] = df_copy['description'].astype(str).str.slice(0, 150) + '...'
        html_chunk += df_copy.to_html(classes='data table table-striped', header="true", index=False, escape=False)
    else:
        html_chunk += "<p>Nincsenek nem releváns adatok.</p>"
    tables.append(html_chunk)

    return render_template('data_table.html', tables=tables, titles=['Adatok'])

@app.route('/query', methods=['GET'])
def query_interface():
    """Lekérdezési felület (SQL és Chat tabok)."""
    return render_template('query_interface.html')

@app.route('/sql-query', methods=['GET', 'POST'])
def sql_query():
    """SQL lekérdező felület a DuckDB segítségével."""
    query = "SELECT district, COUNT(*) as count FROM relevant_data GROUP BY district ORDER BY count DESC;"
    results_html = None
    error = None

    if request.method == 'POST':
        query = request.form.get('query')
        try:
            if not os.path.exists(RELEVANT_FILE):
                raise FileNotFoundError("A feldolgozott adatfájl (core_layer_filtered.parquet) nem található.")
            # A DuckDB közvetlenül tud Parquet fájlokat lekérdezni
            con = duckdb.connect(database=':memory:', read_only=False)
            con.execute(f"CREATE OR REPLACE VIEW relevant_data AS SELECT * FROM read_parquet('{RELEVANT_FILE}');")
            result_df = con.execute(query).fetchdf()
            results_html = result_df.to_html(classes='data table table-striped', header="true", index=False)
        except Exception as e:
            error = f"Hiba a lekérdezés végrehajtása során: {e}"

    return render_template('sql_query.html', query=query, results_html=results_html, error=error)

@app.route('/chat-query', methods=['POST'])
def chat_query():
    """LLM-alapú természetes nyelvi lekérdezés."""
    import ollama
    
    user_question = request.form.get('question', '').strip()
    
    if not user_question:
        return jsonify({'error': 'Kérlek adj meg egy kérdést!'}), 400
    
    try:
        if not os.path.exists(RELEVANT_FILE):
            raise FileNotFoundError("A feldolgozott adatfájl nem található.")
        
        # Adatok betöltése és séma információk
        df = get_data(RELEVANT_FILE)
        if df.empty:
            return jsonify({'error': 'Nincsenek releváns adatok.'}), 400
        
        # Séma információk az LLM számára
        columns_info = ", ".join(df.columns.tolist())
        sample_data = df.head(3).to_string()
        
        # Prompt az LLM számára SQL generáláshoz
        prompt = f"""Te egy SQL szakértő vagy. A feladatod, hogy a felhasználó természetes nyelvi kérdésére SQL lekérdezést generálj.

Az adatbázisban egy 'relevant_data' nevű tábla van a következő oszlopokkal:
{columns_info}

Minta adatok:
{sample_data}

Fontos tudnivalók:
- Az ár 'price_huf' oszlopban van (forintban)
- A terület 'area_sqm' oszlopban van (négyzetméterben)
- A kerület 'district' oszlopban van (pl. "I. kerület", "VI. kerület")
- Az időbélyegek: 'valid_from' (mikor lett feladva), 'valid_till' (meddig volt aktív)
- Az aktív hirdetések: ahol valid_till >= mai dátum VAGY valid_till IS NULL

Felhasználó kérdése: {user_question}

Válaszolj CSAK egy érvényes SQL SELECT utasítással, semmi mást ne írj! Ne használj backtickeket vagy markdown formázást.
"""
        
        # LLM hívás
        response = ollama.chat(
            model='llama3.2:3b',
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.0}
        )
        
        sql_query = response['message']['content'].strip()
        
        # SQL query tisztítása (ha markdown vagy backtick van benne)
        sql_query = sql_query.replace('```sql', '').replace('```', '').strip()
        
        # SQL futtatása
        con = duckdb.connect(database=':memory:', read_only=False)
        con.execute(f"CREATE OR REPLACE VIEW relevant_data AS SELECT * FROM read_parquet('{RELEVANT_FILE}');")
        result_df = con.execute(sql_query).fetchdf()
        
        # Természetes nyelvi válasz generálása
        result_summary = result_df.to_string()
        
        answer_prompt = f"""A felhasználó ezt kérdezte: "{user_question}"

Az SQL lekérdezés eredménye:
{result_summary}

Adj egy rövid, természetes nyelvi választ a felhasználó kérdésére az eredmények alapján. 
Ha számokat említesz, formázd őket olvashatóan (ezres elválasztók). 
Ha árakról van szó, add hozzá a "Ft" jelölést.
Maximum 3-4 mondat legyen a válasz.
"""
        
        answer_response = ollama.chat(
            model='llama3.2:3b',
            messages=[{'role': 'user', 'content': answer_prompt}],
            options={'temperature': 0.3}
        )
        
        natural_answer = answer_response['message']['content'].strip()
        results_html = result_df.to_html(classes='data table table-striped', header="true", index=False)
        
        return jsonify({
            'answer': natural_answer,
            'sql_query': sql_query,
            'results_html': results_html
        })
        
    except Exception as e:
        return jsonify({'error': f'Hiba történt: {str(e)}'}), 500


def calculate_detailed_stats(df, data_type="releváns"):
    """Részletes statisztikákat számol ki egy DataFrame-ről.
    Args:
        df: A DataFrame, amelyről statisztikát készítünk
        data_type: Az adatok típusa (pl. "releváns" vagy "irreleváns")
    Returns:
        stats_html: HTML táblázat a statisztikákkal, vagy None ha hiba történt
    """
    if df.empty:
        flash(f"Nincsenek {data_type} adatok a részletes statisztikákhoz.", "warning")
        return None

    df = df.copy()

    # Debug: kiírjuk, hogy milyen oszlopok vannak az adatokban
    print(f"Elérhető oszlopok ({data_type}): {df.columns.tolist()}")
    flash(f"Debug - Elérhető oszlopok ({data_type}): {', '.join(df.columns.tolist()[:10])}", "info")
    
    # Aggregációk dinamikus összeállítása a KeyError elkerülése érdekében
    aggregations = {}
    
    # Hirdetések száma (URL vagy article_id alapján, amelyik létezik)
    count_col = 'url' if 'url' in df.columns else 'article_id'
    if count_col in df.columns:
        aggregations['hirdetesek_szama'] = (count_col, 'count')

    # Statisztikák csak akkor, ha az oszlop létezik
    if 'price_huf' in df.columns:
        df['price_huf'] = pd.to_numeric(df['price_huf'], errors='coerce')
        aggregations['atlagar'] = ('price_huf', 'mean')
        aggregations['min_ar'] = ('price_huf', 'min')
        aggregations['max_ar'] = ('price_huf', 'max')
        aggregations['ar_szoras'] = ('price_huf', 'std')
    if 'area_sqm' in df.columns:
        df['area_sqm'] = pd.to_numeric(df['area_sqm'], errors='coerce')
        aggregations['atlag_nm'] = ('area_sqm', 'mean')
    if 'rooms' in df.columns:
        df['rooms'] = pd.to_numeric(df['rooms'], errors='coerce')
        aggregations['atlag_szobaszam'] = ('rooms', 'mean')
    if 'floor' in df.columns:
        df['floor'] = pd.to_numeric(df['floor'], errors='coerce')
        aggregations['atlag_emelet'] = ('floor', 'mean')

    # Négyzetméterár - már kiszámolt oszlop használata
    if 'price_per_sqm' in df.columns:
        df['price_per_sqm'] = pd.to_numeric(df['price_per_sqm'], errors='coerce')
        aggregations['atlag_ar_per_nm'] = ('price_per_sqm', 'mean')
        aggregations['nm_ar_szoras'] = ('price_per_sqm', 'std')
    
    # Hirdetési élettartam (ha vannak dátum mezők)
    if 'valid_from' in df.columns and 'valid_till' in df.columns:
        df['valid_from'] = pd.to_datetime(df['valid_from'], errors='coerce')
        df['valid_till'] = pd.to_datetime(df['valid_till'], errors='coerce')
        df['days_on_market'] = (df['valid_till'] - df['valid_from']).dt.days
        aggregations['atlag_piacido'] = ('days_on_market', 'mean')
    
    # Ingatlantípusok megoszlása - LLM által kinyert building_type mező használata
    if 'building_type' in df.columns:
        df['is_tegla'] = df['building_type'] == 'tegla'
        df['is_panel'] = df['building_type'] == 'panel'
        aggregations['tegla_arany'] = ('is_tegla', lambda x: x.sum() / len(x) * 100 if len(x) > 0 else 0)
        aggregations['panel_arany'] = ('is_panel', lambda x: x.sum() / len(x) * 100 if len(x) > 0 else 0)
    
    # Lakás vs. ház megoszlás
    if 'property_category' in df.columns:
        df['is_lakas'] = df['property_category'] == 'lakas'
        aggregations['lakas_arany'] = ('is_lakas', lambda x: x.sum() / len(x) * 100 if len(x) > 0 else 0)
    
    # Terasz megléte
    if 'has_terrace' in df.columns:
        df['has_terrace'] = df['has_terrace'].astype(bool)
        aggregations['terasz_arany'] = ('has_terrace', lambda x: x.sum() / len(x) * 100 if len(x) > 0 else 0)

    if 'district' not in df.columns:
        flash(f"A csoportosításhoz szükséges 'district' oszlop hiányzik a {data_type} adatokból.", "danger")
        return None
    if len(aggregations) <= 1: # Ha csak a darabszám van (vagy még az se), nincs értelme a részletes statisztikának
        flash(f"A {data_type} adatok nem tartalmaznak elegendő numerikus oszlopot (pl. price, size) a részletes statisztikához.", "warning")
        return None

    # Csoportosítás és aggregálás
    district_stats = df.groupby('district').agg(**aggregations).reset_index()

    # Eredmények formázása a megjelenítéshez
    def format_or_na(series, format_str):
        return series.apply(lambda x: format_str.format(x) if pd.notna(x) else 'N/A')

    if 'atlagar' in district_stats.columns: district_stats['atlagar'] = format_or_na(district_stats['atlagar'], '{:,.0f} Ft')
    if 'min_ar' in district_stats.columns: district_stats['min_ar'] = format_or_na(district_stats['min_ar'], '{:,.0f} Ft')
    if 'max_ar' in district_stats.columns: district_stats['max_ar'] = format_or_na(district_stats['max_ar'], '{:,.0f} Ft')
    if 'ar_szoras' in district_stats.columns: district_stats['ar_szoras'] = format_or_na(district_stats['ar_szoras'], '{:,.0f} Ft')
    if 'atlag_nm' in district_stats.columns: district_stats['atlag_nm'] = format_or_na(district_stats['atlag_nm'], '{:,.1f} m²')
    if 'atlag_szobaszam' in district_stats.columns: district_stats['atlag_szobaszam'] = format_or_na(district_stats['atlag_szobaszam'], '{:,.1f}')
    if 'atlag_emelet' in district_stats.columns: district_stats['atlag_emelet'] = format_or_na(district_stats['atlag_emelet'], '{:,.1f}')
    if 'atlag_ar_per_nm' in district_stats.columns: district_stats['atlag_ar_per_nm'] = format_or_na(district_stats['atlag_ar_per_nm'], '{:,.0f} Ft/m²')
    if 'nm_ar_szoras' in district_stats.columns: district_stats['nm_ar_szoras'] = format_or_na(district_stats['nm_ar_szoras'], '{:,.0f} Ft/m²')
    if 'atlag_piacido' in district_stats.columns: district_stats['atlag_piacido'] = format_or_na(district_stats['atlag_piacido'], '{:,.0f} nap')
    if 'tegla_arany' in district_stats.columns: district_stats['tegla_arany'] = format_or_na(district_stats['tegla_arany'], '{:,.1f}%')
    if 'panel_arany' in district_stats.columns: district_stats['panel_arany'] = format_or_na(district_stats['panel_arany'], '{:,.1f}%')
    if 'lakas_arany' in district_stats.columns: district_stats['lakas_arany'] = format_or_na(district_stats['lakas_arany'], '{:,.1f}%')
    if 'terasz_arany' in district_stats.columns: district_stats['terasz_arany'] = format_or_na(district_stats['terasz_arany'], '{:,.1f}%')
        
    # Oszlopnevek átnevezése
    rename_dict = {
        'district': 'Kerület', 
        'hirdetesek_szama': 'Hirdetések száma', 
        'atlagar': 'Átlagár', 
        'min_ar': 'Min. ár',
        'max_ar': 'Max. ár',
        'ar_szoras': 'Ár szórás',
        'atlag_nm': 'Átlagos méret', 
        'atlag_szobaszam': 'Átlagos szobaszám', 
        'atlag_emelet': 'Átlagos emelet',
        'atlag_ar_per_nm': 'Átlagos nm-ár',
        'nm_ar_szoras': 'Nm-ár szórás',
        'atlag_piacido': 'Átlagos piaci idő',
        'tegla_arany': 'Tégla arány',
        'panel_arany': 'Panel arány',
        'lakas_arany': 'Lakás arány',
        'terasz_arany': 'Terasz/erkély arány'
    }
    existing_rename_keys = {k: v for k, v in rename_dict.items() if k in district_stats.columns}
    district_stats.rename(columns=existing_rename_keys, inplace=True)

    stats_html = district_stats.to_html(classes='data table table-striped', header="true", index=False, escape=False)
    return stats_html

@app.route('/detailed-stats')
def detailed_stats():
    """Részletes statisztikákat jelenít meg a releváns adatokról."""
    df = get_data(RELEVANT_FILE)
    stats_html = calculate_detailed_stats(df, "releváns")
    
    if stats_html is None:
        return redirect(url_for('stats'))

    return render_template('detailed_stats.html', stats_table=stats_html, data_type="Releváns")

@app.route('/detailed-stats-irrelevant')
def detailed_stats_irrelevant():
    """Részletes statisztikákat jelenít meg az irreleváns adatokról."""
    df = get_data(IRRELEVANT_FILE)
    stats_html = calculate_detailed_stats(df, "irreleváns")
    
    if stats_html is None:
        return redirect(url_for('stats'))

    return render_template('detailed_stats.html', stats_table=stats_html, data_type="Irreleváns")

@app.route('/map')
def map_view():
    """Térképes megjelenítés. Kerülethatárokkal, ha a geojson fájl elérhető."""
    df = get_data(RELEVANT_FILE)
    m = folium.Map(location=[47.4979, 19.0402], zoom_start=11)
    geojson_path = os.path.join(STATIC_DIR, 'budapest_districts.geojson')
    if os.path.exists(geojson_path):
        with open(geojson_path, encoding='utf-8') as f:
            geojson_data = json.load(f)
        # Automatikusan keressük meg a kerületnév mezőt az első feature-ben
        name_field = None
        if geojson_data['features']:
            prop_keys = list(geojson_data['features'][0]['properties'].keys())
            for key in prop_keys:
                if key.lower() in ['name', 'nev', 'kerulet', 'kerület', 'admin_leve']:
                    name_field = key
                    break
            if not name_field:
                # fallback: első property mező
                name_field = prop_keys[0]
        else:
            name_field = 'name'
        
        # Hirdetések száma kerületenként
        district_counts = {}
        if not df.empty and 'district' in df.columns:
            district_counts = df.groupby('district').size().to_dict()
        
        # Popup készítése minden kerülethez
        for feature in geojson_data['features']:
            district_name = feature['properties'].get(name_field, 'Ismeretlen')
            count = district_counts.get(district_name, 0)
            popup_html = f"<b>{district_name}</b><br>Hirdetések száma: {count}"
            feature['properties']['popup'] = popup_html
        
        folium.GeoJson(
            geojson_data,
            name='keruletek',
            style_function=lambda feature: {
                'fillColor': 'yellow',
                'color': 'black',
                'weight': 1,
                'fillOpacity': 0.1
            },
            highlight_function=lambda feature: {
                'fillColor': 'orange',
                'color': 'red',
                'weight': 3,
                'fillOpacity': 0.5
            },
            popup=folium.GeoJsonPopup(fields=['popup'], labels=False)
        ).add_to(m)
        flash(f"Kerülethatárok megjelenítve a geojson alapján (mező: {name_field}).", "success")
    else:
        flash("A budapest_districts.geojson fájl nem található a static mappában!", "danger")
    
    # CSS injektálás a popup tip (háromszög) és marker ikonok eltávolításához
    css = """
    <style>
    .leaflet-popup-tip {
        display: none !important;
    }
    .leaflet-marker-icon {
        display: none !important;
    }
    .leaflet-marker-shadow {
        display: none !important;
    }
    </style>
    """
    m.get_root().html.add_child(folium.Element(css))
    
    os.makedirs(STATIC_DIR, exist_ok=True)
    m.save(MAP_OUTPUT_FILE)
    return render_template('map.html', map_file='map_render.html')

@app.route('/price-trends')
def price_trends_view():
    """Ártrend elemzés oldal."""
    return render_template('price_trends.html')

@app.route('/analyze-trends', methods=['POST'])
def analyze_trends():
    """Ártrend elemzés futtatása."""
    from price_trends import analyze_price_trends
    
    try:
        df = get_data(RELEVANT_FILE)
        if df.empty:
            return jsonify({'error': 'Nincsenek releváns adatok.'}), 400
        
        # Paraméterek
        district = request.form.get('district', None)
        if district == '':
            district = None
        
        area_min = request.form.get('area_min', None)
        area_max = request.form.get('area_max', None)
        lookback_months = int(request.form.get('lookback_months', 12))
        
        if area_min:
            area_min = float(area_min)
        if area_max:
            area_max = float(area_max)
        
        # Analízis futtatása
        result = analyze_price_trends(df, district, area_min, area_max, lookback_months)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': f'Hiba történt: {str(e)}'}), 500

@app.route('/prediction')
def prediction():
    """Az ML predikciós oldal."""
    import pickle
    
    model_file = os.path.join(WORKSPACE_DIR, 'price_prediction_model.pkl')
    
    # Check if model exists
    model_exists = os.path.exists(model_file)
    metrics = None
    feature_importance = None
    model_name = None
    all_results = None
    
    if model_exists:
        try:
            with open(model_file, 'rb') as f:
                model_data = pickle.load(f)
            metrics = model_data.get('metrics', {})
            feature_importance = model_data.get('feature_importance', [])[:10]  # Top 10
            model_name = model_data.get('model_name', 'Unknown')
            all_results = model_data.get('all_results', [])
        except Exception as e:
            flash(f"Hiba a modell betöltésekor: {e}", "danger")
    
    return render_template('prediction.html', 
                         model_exists=model_exists, 
                         metrics=metrics,
                         feature_importance=feature_importance,
                         model_name=model_name,
                         all_results=all_results)

@app.route('/train-model', methods=['POST'])
@admin_required
def train_model_route():
    """Elindítja a modell tanítását."""
    try:
        subprocess.Popen(["python", os.path.join(APP_DIR, 'train_model.py')])
        flash('A modell tanítása elindult a háttérben. Ez néhány percet vehet igénybe.', 'info')
    except Exception as e:
        flash(f'Hiba történt a modell tanítás indításakor: {e}', 'danger')
    return redirect(url_for('prediction'))

@app.route('/predict-price', methods=['POST'])
def predict_price():
    """Árpredikció egy adott ingatlanra."""
    import pickle
    import pandas as pd
    
    model_file = os.path.join(WORKSPACE_DIR, 'price_prediction_model.pkl')
    
    if not os.path.exists(model_file):
        return jsonify({'error': 'A modell még nincs betanítva!'}), 400
    
    try:
        # Load model
        with open(model_file, 'rb') as f:
            model_data = pickle.load(f)
        
        model = model_data['model']
        model_name = model_data.get('model_name', 'Unknown')
        scaler = model_data.get('scaler')
        feature_names = model_data['feature_names']
        
        # Get input from form
        area_sqm = float(request.form.get('area_sqm', 0))
        rooms = float(request.form.get('rooms', 0))
        floor = float(request.form.get('floor', 0))
        district = request.form.get('district', '')
        building_type = request.form.get('building_type', 'unknown')
        property_category = request.form.get('property_category', 'unknown')
        has_terrace = request.form.get('has_terrace', 'false') == 'true'
        
        # Create feature dataframe
        input_data = pd.DataFrame([{
            'rooms': rooms,
            'area_sqm': area_sqm,
            'floor': floor,
            'has_terrace': int(has_terrace),
            'delivery_year': 2026,
            'delivery_month': 1,
            'delivery_quarter': 1,
            'delivery_dayofweek': 0,
            'has_street_info': 0
        }])
        
        # Add district dummies
        for fname in feature_names:
            if fname.startswith('district_'):
                district_name = fname.replace('district_', '')
                input_data[fname] = 1 if district == district_name else 0
        
        # Add building type dummies
        for fname in feature_names:
            if fname.startswith('building_'):
                btype = fname.replace('building_', '')
                input_data[fname] = 1 if building_type == btype else 0
        
        # Add property category dummies
        for fname in feature_names:
            if fname.startswith('category_'):
                pcat = fname.replace('category_', '')
                input_data[fname] = 1 if property_category == pcat else 0
        
        # Ensure all features are present
        for fname in feature_names:
            if fname not in input_data.columns:
                input_data[fname] = 0
        
        # Reorder columns to match training
        input_data = input_data[feature_names]
        
        # Scale if needed (Neural Network, SVM, KNN)
        if scaler is not None:
            input_data_scaled = scaler.transform(input_data)
            predicted_log_price = model.predict(input_data_scaled)[0]
        else:
            # Predict (log scale-en van)
            predicted_log_price = model.predict(input_data)[0]
        
        # Vissza-transzformálás log-ból
        predicted_price = np.exp(predicted_log_price)
        
        return jsonify({
            'predicted_price': float(predicted_price),
            'formatted_price': f'{predicted_price:,.0f} Ft',
            'price_per_sqm': f'{predicted_price/area_sqm:,.0f} Ft/m²' if area_sqm > 0 else 'N/A'
        })
        
    except Exception as e:
        return jsonify({'error': f'Hiba a predikció során: {str(e)}'}), 500

# --- Cache Admin Endpointok ---

@app.route('/admin/cache')
def cache_admin():
    """Cache Admin felület megjelenítése"""
    return render_template('cache_admin.html')

@app.route('/admin/cache/stats')
def admin_cache_stats():
    """LLM cache statisztikák lekérdezése"""
    try:
        stats = get_cache_stats()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/admin/ml/stats')
def admin_ml_stats():
    """ML Worker Filter statisztikák lekérdezése"""
    try:
        ml_filter = get_ml_filter()
        stats = ml_filter.get_stats()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/admin/ml/retrain', methods=['POST'])
def admin_ml_retrain():
    """ML Worker Filter újratanítása"""
    try:
        success = train_ml_filter_from_llm_log()
        if success:
            ml_stats = get_ml_filter().get_stats()
            return jsonify({
                'success': True,
                'message': f'ML filter újratanítva: {ml_stats["relevant_samples"]} releváns, {ml_stats["irrelevant_samples"]} irreleváns minta',
                'stats': ml_stats
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Nincs elég tréningadat'
            }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/admin/connection/stats')
def admin_connection_stats():
    """HTTP Connection Pool statisztikák lekérdezése"""
    try:
        stats = get_connection_pool_stats()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/admin/incremental/stats')
def admin_incremental_stats():
    """Inkrementális feldolgozás statisztikák lekérdezése"""
    try:
        incremental = get_incremental_processor()
        stats = incremental.get_stats()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/admin/incremental/reset', methods=['POST'])
@admin_required
def admin_incremental_reset():
    """Inkrementális metadata törlése (teljes újrafeldolgozáshoz)"""
    try:
        incremental = get_incremental_processor()
        incremental.reset_metadata()
        return jsonify({
            'success': True,
            'message': 'Inkrementális metadata törölve - következő futtatás teljes feldolgozás lesz'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/admin/cache/clear', methods=['POST'])
@admin_required
def admin_cache_clear():
    """LLM cache tartalmának törlése"""
    try:
        count = clear_cache()
        return jsonify({
            'success': True,
            'message': f'Cache törölve: {count} elem',
            'cleared_count': count
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    # SocketIO-val indítás WebSocket támogatásért
    # A 0.0.0.0 host szükséges, hogy a Docker konténeren kívülről is elérhető legyen.
    socketio.run(app, host='0.0.0.0', port=5001, debug=True, allow_unsafe_werkzeug=True)