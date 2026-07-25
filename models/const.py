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

# Nota: los parámetros del scoring RFM (recencia, frecuencia, cortes de score)
# son campos configurables en mrp.reschedule.config (rfm_recency_*, rfm_freq_*,
# rfm_score_*); sus defaults viven en la definición de cada campo.
