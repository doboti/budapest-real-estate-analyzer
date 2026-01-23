import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor, StackingRegressor
from sklearn.svm import SVR
from sklearn.neighbors import KNeighborsRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import pickle
import os
try:
    from xgboost import XGBRegressor
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

# Paths
DATA_FILE = '/workspace/core_layer_filtered.parquet'
MODEL_FILE = '/workspace/price_prediction_model.pkl'
METRICS_FILE = '/workspace/model_metrics.json'

def prepare_features(df):
    """Feature engineering és előkészítés - csak a megadott változókkal."""
    df = df.copy()
    
    # Csak azokat tartjuk meg, ahol az ár és a terület ismert
    df = df.dropna(subset=['price_huf', 'area_sqm'])
    df = df[df['price_huf'] > 0]
    df = df[df['area_sqm'] > 0]
    
    # ===== OUTLIER SZŰRÉS =====
    # Csak reális lakásárak: 15M - 300M Ft
    df = df[(df['price_huf'] >= 15_000_000) & (df['price_huf'] <= 300_000_000)]
    
    # Csak releváns hirdetések
    if 'relevant' in df.columns:
        df = df[df['relevant'] == True]
    
    # ===== FEATURE-ÖK =====
    features = pd.DataFrame()
    
    # Numerikus változók
    features['rooms'] = df['rooms'].fillna(df['rooms'].median())
    features['area_sqm'] = df['area_sqm']
    features['floor'] = df['floor'].fillna(0)
    
    # Terasz
    if 'has_terrace' in df.columns:
        features['has_terrace'] = df['has_terrace'].fillna(False).infer_objects(copy=False).astype(int)
    else:
        features['has_terrace'] = 0
    
    # Delivery day (dátum feldolgozás)
    if 'delivery_day' in df.columns:
        df['delivery_day'] = pd.to_datetime(df['delivery_day'], errors='coerce')
        features['delivery_year'] = df['delivery_day'].dt.year.fillna(2025)
        features['delivery_month'] = df['delivery_day'].dt.month.fillna(1)
        features['delivery_quarter'] = df['delivery_day'].dt.quarter.fillna(1)
        features['delivery_dayofweek'] = df['delivery_day'].dt.dayofweek.fillna(0)
    
    # Kerület (one-hot encoding)
    if 'district' in df.columns:
        df['district'] = df['district'].fillna('unknown')
        district_dummies = pd.get_dummies(df['district'], prefix='district', drop_first=True)
        features = pd.concat([features, district_dummies], axis=1)
    
    # Város (valószínűleg mindig Budapest, de hátha)
    if 'city' in df.columns:
        df['city'] = df['city'].fillna('unknown')
        if df['city'].nunique() > 1:
            city_dummies = pd.get_dummies(df['city'], prefix='city', drop_first=True)
            features = pd.concat([features, city_dummies], axis=1)
    
    # Utca - túl sok unique érték, csak azt jelöljük hogy van-e
    if 'street_x' in df.columns:
        features['has_street_info'] = (~df['street_x'].isna()).astype(int)
    
    # Építési mód (building_type)
    if 'building_type' in df.columns:
        df['building_type'] = df['building_type'].fillna('unknown')
        df['building_type'] = df['building_type'].str.lower().str.strip()
        
        # Normalizálás
        building_map = {
            'tegla': 'tegla',
            'tégla': 'tegla',
            'tegla építésű': 'tegla',
            'panel': 'panel',
            'panelprogramos': 'panel',
            'lakópark': 'egyeb',
            'vegyes': 'egyeb',
            'egyeb': 'egyeb',
            'unknown': 'unknown'
        }
        df['building_type'] = df['building_type'].map(lambda x: building_map.get(x, 'unknown'))
        building_dummies = pd.get_dummies(df['building_type'], prefix='building', drop_first=True)
        features = pd.concat([features, building_dummies], axis=1)
    
    # Ingatlan kategória (property_category)
    if 'property_category' in df.columns:
        df['property_category'] = df['property_category'].fillna('unknown')
        property_dummies = pd.get_dummies(df['property_category'], prefix='category', drop_first=True)
        features = pd.concat([features, property_dummies], axis=1)
    
    # ===== LOG TRANSZFORMÁCIÓ =====
    target = np.log(df['price_huf'])
    
    return features, target, features.columns.tolist()

def train_model():
    """ML modellek összehasonlítása és a legjobb kiválasztása."""
    print("Loading data...")
    df = pd.read_parquet(DATA_FILE)
    print(f"Total records: {len(df)}")
    
    print("Preparing features...")
    X, y, feature_names = prepare_features(df)
    print(f"Features prepared: {X.shape}")
    print(f"Feature columns: {feature_names}")
    
    # Train-test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    print(f"Training set: {X_train.shape}, Test set: {X_test.shape}")
    
    # Scaling for SVM, KNN, Neural Network
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # ===== MODELL DEFINÍCIÓK =====
    models = {}
    
    print("\n" + "="*60)
    print("COMPARING MULTIPLE ML MODELS")
    print("="*60)
    
    # 1. Random Forest
    print("\n[1/6] Training Random Forest...")
    models['Random Forest'] = RandomForestRegressor(
        n_estimators=100,
        max_depth=20,
        min_samples_split=10,
        min_samples_leaf=5,
        random_state=42,
        n_jobs=-1
    )
    
    # 2. XGBoost (ha elérhető)
    if HAS_XGBOOST:
        print("[2/6] Training XGBoost...")
        models['XGBoost'] = XGBRegressor(
            n_estimators=100,
            max_depth=10,
            learning_rate=0.1,
            random_state=42,
            n_jobs=-1
        )
    else:
        print("[2/6] XGBoost not available, skipping...")
    
    # 3. Neural Network
    print("[3/6] Training Neural Network...")
    models['Neural Network'] = MLPRegressor(
        hidden_layer_sizes=(100, 50, 25),
        activation='relu',
        solver='adam',
        max_iter=500,
        random_state=42,
        early_stopping=True
    )
    
    # 4. SVM
    print("[4/6] Training SVM...")
    models['SVM'] = SVR(
        kernel='rbf',
        C=100,
        epsilon=0.1,
        gamma='scale'
    )
    
    # 5. KNN
    print("[5/6] Training KNN...")
    models['KNN'] = KNeighborsRegressor(
        n_neighbors=10,
        weights='distance',
        n_jobs=-1
    )
    
    # 6. Stacking Ensemble
    print("[6/6] Training Stacking Ensemble...")
    base_models = [
        ('rf', RandomForestRegressor(n_estimators=50, max_depth=15, random_state=42, n_jobs=-1)),
        ('ridge', Ridge(alpha=1.0))
    ]
    if HAS_XGBOOST:
        base_models.append(('xgb', XGBRegressor(n_estimators=50, max_depth=8, random_state=42, n_jobs=-1)))
    
    models['Stacking Ensemble'] = StackingRegressor(
        estimators=base_models,
        final_estimator=Ridge(alpha=1.0),
        n_jobs=-1
    )
    
    # ===== TRAINING ÉS ÉRTÉKELÉS =====
    results = []
    best_model_name = None
    best_r2 = -999
    best_model = None
    best_feature_importance = None
    
    for model_name, model in models.items():
        print(f"\nTraining {model_name}...")
        
        # Scaled vs non-scaled
        if model_name in ['Neural Network', 'SVM', 'KNN']:
            model.fit(X_train_scaled, y_train)
            y_pred_train = model.predict(X_train_scaled)
            y_pred_test = model.predict(X_test_scaled)
        else:
            model.fit(X_train, y_train)
            y_pred_train = model.predict(X_train)
            y_pred_test = model.predict(X_test)
        
        # Vissza-transzformálás log-ból
        y_pred_train_original = np.exp(y_pred_train)
        y_pred_test_original = np.exp(y_pred_test)
        y_train_original = np.exp(y_train)
        y_test_original = np.exp(y_test)
        
        # Metrics
        test_r2 = r2_score(y_test_original, y_pred_test_original)
        test_mae = mean_absolute_error(y_test_original, y_pred_test_original)
        test_rmse = np.sqrt(mean_squared_error(y_test_original, y_pred_test_original))
        test_mape = np.mean(np.abs((y_test_original - y_pred_test_original) / y_test_original)) * 100
        test_mae_log = mean_absolute_error(y_test, y_pred_test)
        
        results.append({
            'model': model_name,
            'test_r2': test_r2,
            'test_mae': test_mae,
            'test_rmse': test_rmse,
            'test_mape': test_mape,
            'test_mae_log': test_mae_log
        })
        
        print(f"  → R²: {test_r2:.4f} | MAPE: {test_mape:.2f}% | MAE: {test_mae:,.0f} Ft")
        
        # Track best model
        if test_r2 > best_r2:
            best_r2 = test_r2
            best_model_name = model_name
            best_model = model
            
            # Feature importance (ha van)
            if hasattr(model, 'feature_importances_'):
                best_feature_importance = pd.DataFrame({
                    'feature': feature_names,
                    'importance': model.feature_importances_
                }).sort_values('importance', ascending=False)
    
    # ===== EREDMÉNYEK =====
    print("\n" + "="*60)
    print("MODEL COMPARISON RESULTS")
    print("="*60)
    results_df = pd.DataFrame(results).sort_values('test_r2', ascending=False)
    print(results_df.to_string(index=False))
    
    print(f"\n🏆 BEST MODEL: {best_model_name}")
    print(f"   R² = {best_r2:.4f}")
    
    # Feature importance
    if best_feature_importance is not None:
        print("\n🔝 Top 10 Most Important Features:")
        print(best_feature_importance.head(10).to_string(index=False))
    
    # ===== SAVE BEST MODEL =====
    model_data = {
        'model': best_model,
        'model_name': best_model_name,
        'scaler': scaler if best_model_name in ['Neural Network', 'SVM', 'KNN'] else None,
        'feature_names': feature_names,
        'metrics': results_df.iloc[0].to_dict(),
        'all_results': results_df.to_dict('records'),
        'feature_importance': best_feature_importance.to_dict('records') if best_feature_importance is not None else None
    }
    
    with open(MODEL_FILE, 'wb') as f:
        pickle.dump(model_data, f)
    
    print(f"\n✅ Best model ({best_model_name}) saved to {MODEL_FILE}")
    
    return model_data

if __name__ == '__main__':
    train_model()
