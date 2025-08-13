import pandas as pd
import numpy as np
from faker import Faker
import random
from datetime import datetime
import os
from sqlalchemy import create_engine

# --- НАСТРОЙКИ ---
# Создаём директорию для сохранения CSV файлов
os.makedirs("generated_data", exist_ok=True)

# Инициализация генераторов с фиксированным seed для воспроизводимости результатов
fake = Faker('ru_RU')
Faker.seed(42)
np.random.seed(42)

# ================================
# 1. ПАРАМЕТРЫ ГЕНЕРАЦИИ
# ================================
N_CLIENTS = 500
N_PRODUCTS = 100
N_DEALS = 10000
START_DATE = "2024-01-01"
END_DATE = "2025-12-31"

# Справочники
regions = ["Минская", "Гомельская", "Витебская", "Могилёвская", "Брестская", "Гродненская"]
stages = ["Лид", "Контакт установлен", "Переговоры", "Предложение отправлено", "Сделка закрыта"]
cost_categories = ["Контекстная реклама", "SEO", "Зарплата отдела маркетинга", "Мероприятия", "SMM"]
product_categories = ['Оборудование', 'Техника', 'Экипировка', 'Комплектующие', 'Электроника', 'Инструменты']

# ================================
# 2. ГЕНЕРАЦИЯ СПРАВОЧНИКОВ (Dimensions)
# ================================

# --- sales.d_calendar ---
month_names_ru = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель', 5: 'Май', 6: 'Июнь',
    7: 'Июль', 8: 'Август', 9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
}
dates = pd.date_range(START_DATE, END_DATE, freq='D')
calendar_data = [
    {'date_id': int(d.strftime('%Y%m%d')), 'full_date': d.date(), 'year': d.year, 'month_name': month_names_ru[d.month],
     'quarter': d.quarter} for d in dates]
df_calendar = pd.DataFrame(calendar_data)
date_ids = df_calendar['date_id'].tolist()

# --- sales.d_clients ---
clients_data = [{'client_id': i, 'client_name': fake.company(), 'region': random.choice(regions),
                 'registration_date': fake.date_between(start_date='-2y', end_date='today')} for i in
                range(1, N_CLIENTS + 1)]
df_clients = pd.DataFrame(clients_data)
client_ids = df_clients['client_id'].tolist()

# --- sales.d_products ---
products_data = [
    {'product_id': i, 'product_name': f"Товар {i}", 'abc_group': np.random.choice(['A', 'B', 'C'], p=[0.2, 0.3, 0.5]),
     'xyz_group': np.random.choice(['X', 'Y', 'Z'], p=[0.3, 0.4, 0.3]), 'category': random.choice(product_categories)}
    for i in range(1, N_PRODUCTS + 1)]
df_products = pd.DataFrame(products_data)
product_ids = df_products['product_id'].tolist()

# ================================
# 3. ГЕНЕРАЦИЯ ТАБЛИЦ ФАКТОВ И ВИТРИН
# ================================

# --- sales.f_deals ---
deals_data = []
base_prices = {'A': 550, 'B': 220, 'C': 60}
for i in range(1, N_DEALS + 1):
    product_id = random.choice(product_ids)
    abc_group = df_products.loc[df_products['product_id'] == product_id, 'abc_group'].values[0]

    # Генерация выручки
    base_price = base_prices[abc_group]
    revenue = round(np.random.normal(base_price, base_price * 0.3), 2)
    revenue = max(revenue, 10)
    quantity = np.random.poisson(1) + 1
    revenue_byn = round(revenue * quantity, 2)

    # Генерация этапа воронки
    stage_probabilities = [0.40, 0.25, 0.15, 0.10, 0.10]  # Больше лидов, меньше закрытых сделок
    stage_name = np.random.choice(stages, p=stage_probabilities)

    # !Выручка присваивается только успешно закрытым сделкам.
    if stage_name != "Сделка закрыта":
        revenue_byn = 0

    deals_data.append({
        'deal_id': i,
        'date_id': random.choice(date_ids),
        'client_id': random.choice(client_ids),
        'product_id': product_id,
        'revenue_byn': revenue_byn,
        'quantity': quantity,
        'stage_name': stage_name,
    })
df_deals = pd.DataFrame(deals_data)

# --- РАСЧЕТ ФЛАГА is_first_deal ---
print("Рассчитываем флаг первой сделки для каждого клиента...")
df_deals.sort_values(by=['client_id', 'date_id'], inplace=True)
first_deal_indices = df_deals.drop_duplicates(subset=['client_id'], keep='first').index
df_deals['is_first_deal'] = False
df_deals.loc[first_deal_indices, 'is_first_deal'] = True

# --- analytics.mart_client_metrics ---
print("Рассчитываем метрики клиентов (LTV)...")
metrics_data = []
for client_id in client_ids:
    avg_freq = round(np.random.exponential(1.5), 2)
    avg_freq = min(avg_freq, 12)
    lifetime = np.random.randint(6, 60)

    client_deals = df_deals[df_deals['client_id'] == client_id]

    # РАСЧЕТ СРЕДНЕГО ЧЕКА: Учитываем только сделки с выручкой > 0
    successful_deals = client_deals[client_deals['revenue_byn'] > 0]
    avg_check = successful_deals['revenue_byn'].mean() if not successful_deals.empty else 0

    ltv = avg_check * avg_freq * (lifetime / 12)
    ltv = round(ltv, 2) if not pd.isna(ltv) else 0

    rfm_options = ["Champions", "Loyal Customer", "Potential Loyalist", "New Customers", "At Risk", "Hibernating"]
    rfm_segment = np.random.choice(rfm_options, p=[0.15, 0.15, 0.2, 0.2, 0.15, 0.15])

    metrics_data.append(
        {'client_id': client_id, 'avg_purchase_frequency': avg_freq, 'predicted_lifetime_months': lifetime,
         'ltv_byn': ltv, 'rfm_segment': rfm_segment})
df_metrics = pd.DataFrame(metrics_data)

# --- marketing.costs & sales.d_plans ---
month_starts = [d.strftime('%Y%m%d') for d in pd.date_range(START_DATE, END_DATE, freq='MS')]
costs_data = []
plans_data = []

for month_id in month_starts:
    # Затраты
    for _ in range(3):
        costs_data.append({'cost_id': len(costs_data) + 1, 'date_id': int(month_id),
                           'total_cost_byn': round(random.uniform(5000, 20000), 2),
                           'cost_category': random.choice(cost_categories)})
    # Планы
    for region in regions:
        plans_data.append({'plan_id': len(plans_data) + 1, 'date_id': int(month_id), 'region': region,
                           'plan_revenue_byn': round(random.uniform(25000, 55000), 2)})

df_costs = pd.DataFrame(costs_data)
df_plans = pd.DataFrame(plans_data)

# ================================
# 4. СОХРАНЕНИЕ И ЗАГРУЗКА
# ================================

# --- Сохранение в CSV ---
df_calendar.to_csv('generated_data/sales_d_calendar.csv', index=False)
df_clients.to_csv('generated_data/sales_d_clients.csv', index=False)
df_products.to_csv('generated_data/sales_d_products.csv', index=False)
df_deals.to_csv('generated_data/sales_f_deals.csv', index=False)
df_metrics.to_csv('generated_data/analytics_mart_client_metrics.csv', index=False)
df_costs.to_csv('generated_data/marketing_costs.csv', index=False)
df_plans.to_csv('generated_data/sales_d_plans.csv', index=False)

print("\n✅ Все данные сгенерированы и сохранены в CSV в папке 'generated_data/'")

# --- Загрузка в PostgreSQL с логами и chunksize ---
try:
    engine = create_engine(
        'postgresql://postgres:1231@localhost:5432/kpi_sales_db?client_encoding=utf8',
        connect_args={'connect_timeout': 10}
    )

    print("\nЗагружаем данные в PostgreSQL (таблицы будут перезаписаны)...")

    # Устанавливаем размер чанка
    CHUNK_SIZE = 1000

    print("1/7: Загрузка sales.d_calendar...")
    df_calendar.to_sql('d_calendar', engine, schema='sales', if_exists='replace', index=False, method='multi',
                       chunksize=CHUNK_SIZE)

    print("2/7: Загрузка sales.d_clients...")
    df_clients.to_sql('d_clients', engine, schema='sales', if_exists='replace', index=False, method='multi',
                      chunksize=CHUNK_SIZE)

    print("3/7: Загрузка sales.d_products...")
    df_products.to_sql('d_products', engine, schema='sales', if_exists='replace', index=False, method='multi',
                       chunksize=CHUNK_SIZE)

    print("4/7: Загрузка sales.f_deals...")
    df_deals.to_sql('f_deals', engine, schema='sales', if_exists='replace', index=False, method='multi',
                    chunksize=CHUNK_SIZE)

    print("5/7: Загрузка analytics.mart_client_metrics...")
    df_metrics.to_sql('mart_client_metrics', engine, schema='analytics', if_exists='replace', index=False,
                      method='multi', chunksize=CHUNK_SIZE)

    print("6/7: Загрузка marketing.costs...")
    df_costs.to_sql('costs', engine, schema='marketing', if_exists='replace', index=False, method='multi',
                    chunksize=CHUNK_SIZE)

    print("7/7: Загрузка sales.d_plans...")
    df_plans.to_sql('d_plans', engine, schema='sales', if_exists='replace', index=False, method='multi',
                    chunksize=CHUNK_SIZE)

    print("\n✅ Все данные успешно загружены в PostgreSQL.")

except Exception as e:
    print(f"\n⚠️ Ошибка при загрузке данных в PostgreSQL: {e}")
    print("   Убедитесь, что Docker-контейнер с PostgreSQL запущен и параметры подключения верны.")