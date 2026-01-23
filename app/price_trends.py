import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

def analyze_price_trends(df, district=None, area_min=None, area_max=None, lookback_months=12):
    """
    Árelemzés idősorok alapján kerület és méret szerint szűrve.
    
    Args:
        df: DataFrame a hirdetésekkel
        district: Kerület szűrés (pl. "II. kerület")
        area_min: Minimum terület (m²)
        area_max: Maximum terület (m²)
        lookback_months: Hány hónapot nézzen vissza
    
    Returns:
        dict: Eredmények és előrejelzés
    """
    df = df.copy()
    
    # Szűrések
    if district:
        df = df[df['district'] == district]
    if area_min:
        df = df[df['area_sqm'] >= area_min]
    if area_max:
        df = df[df['area_sqm'] <= area_max]
    
    # Csak releváns és árral rendelkező hirdetések
    if 'relevant' in df.columns:
        df = df[df['relevant'] == True]
    df = df.dropna(subset=['price_huf', 'delivery_day'])
    
    # Delivery day dátummá alakítása
    df['delivery_day'] = pd.to_datetime(df['delivery_day'], errors='coerce')
    df = df.dropna(subset=['delivery_day'])
    
    # Lookback időszak
    cutoff_date = datetime.now() - timedelta(days=lookback_months*30)
    df = df[df['delivery_day'] >= cutoff_date]
    
    if len(df) < 10:
        return {
            'error': 'Kevés adat az elemzéshez (minimum 10 hirdetés szükséges)',
            'count': len(df)
        }
    
    # Havi aggregálás
    df['year_month'] = df['delivery_day'].dt.to_period('M')
    monthly_stats = df.groupby('year_month').agg({
        'price_huf': ['mean', 'median', 'count'],
        'price_per_sqm': ['mean', 'median'],
        'area_sqm': 'mean'
    }).reset_index()
    
    monthly_stats.columns = ['year_month', 'avg_price', 'median_price', 'count', 
                              'avg_price_per_sqm', 'median_price_per_sqm', 'avg_area']
    monthly_stats['year_month_str'] = monthly_stats['year_month'].astype(str)
    
    # Trend számítás (lineáris regresszió)
    monthly_stats['month_index'] = range(len(monthly_stats))
    
    if len(monthly_stats) >= 3:
        # Lineáris trend a price_per_sqm-re
        from sklearn.linear_model import LinearRegression
        
        X = monthly_stats[['month_index']].values
        y = monthly_stats['avg_price_per_sqm'].values
        
        model = LinearRegression()
        model.fit(X, y)
        
        # Előrejelzés következő 6 hónapra
        future_months = np.arange(len(monthly_stats), len(monthly_stats) + 6).reshape(-1, 1)
        future_predictions = model.predict(future_months)
        
        # Trend irány és mérték
        slope = model.coef_[0]
        current_price = monthly_stats['avg_price_per_sqm'].iloc[-1]
        
        # 6 hónapos előrejelzés
        predicted_6m = future_predictions[-1]
        change_6m = predicted_6m - current_price
        change_percent_6m = (change_6m / current_price) * 100
        
        # Trend értékelés
        if abs(change_percent_6m) < 2:
            trend_label = 'Stagnálás'
            trend_color = 'warning'
        elif change_percent_6m > 0:
            trend_label = 'Drágulás'
            trend_color = 'danger'
        else:
            trend_label = 'Olcsósodás'
            trend_color = 'success'
        
        # Jövőbeli hónapok nevei
        last_date = monthly_stats['year_month'].iloc[-1].to_timestamp()
        future_dates = [last_date + pd.DateOffset(months=i) for i in range(1, 7)]
        future_labels = [d.strftime('%Y-%m') for d in future_dates]
        
        result = {
            'success': True,
            'count': int(df.shape[0]),
            'months_analyzed': len(monthly_stats),
            'current_avg_price_per_sqm': float(current_price),
            'predicted_6m_price_per_sqm': float(predicted_6m),
            'change_6m_absolute': float(change_6m),
            'change_6m_percent': float(change_percent_6m),
            'trend_label': trend_label,
            'trend_color': trend_color,
            'monthly_slope': float(slope),
            'historical_data': {
                'labels': monthly_stats['year_month_str'].tolist(),
                'avg_prices': monthly_stats['avg_price'].tolist(),
                'avg_price_per_sqm': monthly_stats['avg_price_per_sqm'].tolist(),
                'counts': monthly_stats['count'].tolist()
            },
            'forecast_data': {
                'labels': future_labels,
                'predictions': future_predictions.tolist()
            },
            'filters': {
                'district': district,
                'area_min': area_min,
                'area_max': area_max,
                'lookback_months': lookback_months
            }
        }
    else:
        result = {
            'error': 'Túl kevés hónap az elemzéshez (minimum 3 hónap szükséges)',
            'count': len(df),
            'months': len(monthly_stats)
        }
    
    return result
