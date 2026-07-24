SALE_CAT_SELECTION = [
    ('A', 'A — Alta rotación'),
    ('B', 'B'),
    ('C', 'C'),
    ('D', 'D'),
    ('E', 'E — Baja rotación'),
]

DEFAULT_PO_CRITICAL_DAYS = 5

# Umbrales de semáforo para análisis de proveedores (% entregas a tiempo)
DEFAULT_ON_TIME_GREEN_PCT = 90
DEFAULT_ON_TIME_YELLOW_PCT = 70

# Días sin compra a partir del cual un cliente/proveedor se considera en riesgo
DEFAULT_RISK_DAYS = 90

# Días sin rotación a partir del cual se emite alerta de quiebre de stock
DEFAULT_ROTATION_WARN_DAYS = 90

# Umbrales de cobertura de forecast (% respecto al demand objetivo)
FORECAST_WARNING_PCT = 70
FORECAST_CRITICAL_PCT = 50

# Valores por defecto del scoring RFM. Son solo los defaults de los campos configurables
# en mrp.reschedule.config (rfm_recency_*, rfm_freq_*, rfm_score_*); el cálculo lee la config.
RFM_RECENCY_RECENT_DAYS = 30   # R: días desde última compra para "reciente" (3 pts)
RFM_RECENCY_MEDIUM_DAYS = 90   # R: días desde última compra para "media" (2 pts)
RFM_FREQ_HIGH = 10             # F: > N pedidos = alta frecuencia (3 pts)
RFM_FREQ_MEDIUM = 3            # F: ≥ N pedidos = frecuencia media (2 pts)
RFM_SCORE_A = 8                # Score total ≥ este valor = A
RFM_SCORE_B = 6                # Score total ≥ este valor = B
RFM_SCORE_C = 4                # Score total ≥ este valor = C
RFM_SCORE_D = 3                # Score total ≥ este valor = D (resto con datos); menor = E
