# Quartery Robotrader

Optimizador de Cartera de Mínima Varianza Global (GMVP) para el **Mercado Continuo español**. Sistema de rebalanceo trimestral de baja frecuencia que genera instrucciones operativas precisas (número entero de acciones a comprar o vender) sin conexión a ningún bróker ni ejecución automática de órdenes.

---

## Fundamento matemático

El sistema implementa la **Cartera de Mínima Varianza Global (GMVP)**, que resuelve el problema de optimización cuadrática:

```
min  wᵀ Σ w
      w

s.t. 1ᵀw = 1
     0 ≤ wᵢ ≤ 0.20  ∀i
```

A diferencia de la optimización clásica media-varianza de Markowitz, la GMVP prescinde del vector de rendimientos esperados `μ` —cuya estimación introduce un severo error de especificación— y centra el problema exclusivamente en la estimación robusta de la matriz de covarianzas `Σ`.

### Estimador de covarianza: Ledoit-Wolf de correlación constante

Para mitigar el "efecto maximizador de errores" de la covarianza muestral en universos con activos de liquidez fragmentada (característica estructural del Mercado Continuo español), el sistema aplica el estimador de encogimiento lineal de Ledoit-Wolf con objetivo de **correlación constante**:

```
Σ̃ = (1 - δ) · S + δ · F
```

Donde `S` es la covarianza muestral, `F` la matriz objetivo de correlación constante y `δ ∈ [0,1]` el coeficiente de encogimiento óptimo determinado analíticamente minimizando la norma de Frobenius.

### Restricciones de peso y Teorema de Jagannathan-Ma

Las restricciones `0 ≤ wᵢ ≤ 0.20` (long-only + límite de concentración) actúan como **regularización implícita** sobre la matriz de covarianzas (Teorema de Jagannathan-Ma, 2003), garantizando carteras estables con bajo turnover fuera de muestra sin necesidad de estimadores estadísticos más complejos.

---

## Arquitectura modular

```
quartery-robotrader/
├── config.py                  ← Parámetros globales (única fuente de verdad)
├── main.py                    ← Orquestador del pipeline (5 etapas)
├── estado_cartera.json        ← Estado del inversor: efectivo + posiciones
├── requirements.txt
│
├── data/
│   ├── cache_db.py            ← Persistencia SQLite incremental
│   └── ingester.py            ← Ingesta yfinance con rate limiting y caché
│
├── mathematical/
│   └── optimizer.py           ← Ledoit-Wolf + OSQP → SCS fallback
│
├── reconciliation/
│   └── engine.py              ← NAV, pesos actuales, delta operativo
│
└── presentation/
    └── output.py              ← Informe SRRI (UCITS IV) + Semáforo CNMV
```

### Separación de responsabilidades

| Módulo | Responsabilidad | Acoplamiento externo |
|---|---|---|
| `data/cache_db.py` | Persistencia SQLite de series de precios | Ninguno |
| `data/ingester.py` | Único punto de contacto con Yahoo Finance | yfinance, requests |
| `mathematical/optimizer.py` | Estimación Ledoit-Wolf + optimización convexa | PyPortfolioOpt |
| `reconciliation/engine.py` | NAV, pesos actuales y delta con bandas de tolerancia | Ninguno |
| `presentation/output.py` | Formateo regulatorio (SRRI, CNMV) e instrucciones | Ninguno |

---

## Instalación

```bash
git clone https://github.com/Manuel-Insua/quartery-robotrader.git
cd quartery-robotrader
pip install -r requirements.txt
```

**Dependencias opcionales** (mejora la resistencia a bloqueos HTTP 403/999 de Yahoo Finance):
```bash
pip install curl_cffi
```

**Requisitos:** Python 3.10+

---

## Configuración del estado de cartera

Edita `estado_cartera.json` antes de cada ejecución:

```json
{
  "metadata": {
    "fecha_ultimo_rebalanceo": "2026-05-25",
    "divisa": "EUR"
  },
  "efectivo": {
    "disponible": 20000.00,
    "reserva_gastos": 500.00
  },
  "posiciones": {
    "SAN.MC":  {"cantidad": 500, "precio_coste": 3.85},
    "IBE.MC":  {"cantidad": 200, "precio_coste": 11.20},
    "TEF.MC":  {"cantidad": 300, "precio_coste": 4.05},
    "BBVA.MC": {"cantidad": 150, "precio_coste": 8.90}
  }
}
```

| Campo | Descripción |
|---|---|
| `efectivo.disponible` | Saldo líquido total en cuenta (EUR) |
| `efectivo.reserva_gastos` | Colchón excluido de la optimización (comisiones, etc.) |
| `posiciones` | Tickers del Mercado Continuo (sufijo `.MC`) con número de acciones |
| `precio_coste` | Opcional — precio medio de adquisición (no afecta a la optimización) |

El **capital neto disponible** para rebalanceo se calcula como `disponible − reserva_gastos`.

---

## Uso

```bash
python main.py
```

### Ejemplo de salida

```
════════════════════════════════════════════════════════════════════
        OPTIMIZADOR GMVP — MERCADO CONTINUO ESPAÑOL
     Cartera de Mínima Varianza Global · Rebalanceo Trimestral
════════════════════════════════════════════════════════════════════

                      RESUMEN FINANCIERO
  ────────────────────────────────────────────────────────────────
  Fecha último rebalanceo:                          2026-05-25
  Valor total (NAV):                                52,340.00  EUR
  Efectivo neto disponible:                         19,500.00  EUR

              PERFIL DE RIESGO POST-OPTIMIZACIÓN
  ────────────────────────────────────────────────────────────────
  Volatilidad anualizada (GMVP):                       13.847  %
  SRRI (UCITS IV, Directiva KID):
    [█████░░]  5/7  —  Moderado-alto (renta variable baja vol.)
  Semáforo CNMV (Ord. ECC/2316/2015):             Nivel 6 / 6

  ⚠  ADVERTENCIA REGULATORIA CNMV:
     Esta cartera está compuesta íntegramente por renta variable
     española (Nivel 6). No existe garantía de recuperación del
     capital invertido. La inversión puede resultar en pérdida total.

          DISTRIBUCIÓN ÓPTIMA GMVP  (pesos ≥ 0.5 %)
  ────────────────────────────────────────────────────────────────
  Ticker      Peso Óptimo     Capital (EUR)      Precio
  ────────── ────────────  ────────────────  ──────────
  REP.MC           20.00%         10,468.00       14.23
  IBE.MC           20.00%         10,468.00       12.87
  ELE.MC           18.50%          9,682.90       27.14
  SAN.MC           15.30%          8,008.02        4.31
  TEF.MC           14.20%          7,432.28        4.18
  BBVA.MC          12.00%          6,280.80        9.94

                   INSTRUCCIONES OPERATIVAS
  ────────────────────────────────────────────────────────────────
  Operación    Acciones  Ticker         Precio     Importe (EUR)
  ────────── ──────────  ────────── ──────────  ────────────────
  COMPRAR           412  REP.MC          14.23          5,862.76
  COMPRAR           187  IBE.MC          12.87          2,406.69
  COMPRAR            94  BBVA.MC          9.94            934.36
  VENDER            118  TEF.MC           4.18            493.24
```

---

## Pipeline de ejecución

```
[Inicio]
   │
   ▼
[1/5] Carga estado_cartera.json
      └─ Capital neto = disponible − reserva_gastos
   │
   ▼
[2/5] Ingesta y caché SQLite
      ├─ Comprueba última fecha en spanish_market_cache.db
      ├─ Descarga solo el delta incremental (yfinance)
      ├─ Rate limiting: 0.25–0.50 s entre peticiones
      ├─ User-Agent rotativo (anti-bloqueo 403/999)
      └─ ffill(limit=3) para stale prices de activos ilíquidos
   │
   ▼
[3/5] Optimización GMVP
      ├─ Covarianza Ledoit-Wolf (correlación constante, δ analítico)
      ├─ EfficientFrontier con expected_returns=None
      ├─ Solver OSQP (primario)
      └─ Solver SCS (fallback automático si OSQP falla)
   │
   ▼
[4/5] Conciliación y delta operativo
      ├─ NAV = efectivo_neto + Σ(qᵢ · Pᵢ)
      ├─ Δqᵢ = int(NAV · w*ᵢ / Pᵢ) − qᵢ_actual
      └─ Bandas de tolerancia: omite si |Δwᵢ| < 5% (abs) ó |Δwᵢ/w*ᵢ| < 25% (rel)
   │
   ▼
[5/5] Informe de salida
      ├─ SRRI 1–7 (Directiva UCITS IV / KIID)
      └─ Semáforo de riesgo CNMV (Ord. ECC/2316/2015, Nivel 6)
   │
   ▼
[Fin]
```

---

## Parámetros configurables

Todos los parámetros del sistema se centralizan en `config.py`:

| Parámetro | Valor por defecto | Descripción |
|---|---|---|
| `DIAS_HISTORICO` | `756` | Ventana histórica (~3 años bursátiles) |
| `MAX_PESO_ACTIVO` | `0.20` | Límite de concentración máxima por activo (20%) |
| `MIN_COBERTURA` | `0.80` | Cobertura mínima de datos requerida por activo (80%) |
| `MAX_FFILL_DIAS` | `3` | Máximo de días consecutivos de interpolación forward-fill |
| `SLEEP_MIN_S` | `0.25` | Retardo mínimo entre peticiones a Yahoo Finance (segundos) |
| `SLEEP_MAX_S` | `0.50` | Retardo máximo entre peticiones a Yahoo Finance (segundos) |
| `BANDA_TOLERANCIA_ABS` | `0.05` | Banda absoluta de tolerancia de rebalanceo (5%) |
| `BANDA_TOLERANCIA_REL` | `0.25` | Banda relativa de tolerancia de rebalanceo (25%) |

---

## Universo de activos

El sistema optimiza sobre un universo representativo del **IBEX 35** (29 valores), ampliado automáticamente con cualquier activo ya presente en la cartera del inversor:

`ACS.MC · ACX.MC · ANA.MC · BBVA.MC · BKT.MC · CABK.MC · CLNX.MC · COL.MC · ELE.MC · ENG.MC · FER.MC · GRF.MC · IAG.MC · IBE.MC · IDR.MC · ITX.MC · LOG.MC · MAP.MC · NTGY.MC · PHM.MC · RED.MC · REP.MC · ROVI.MC · SAB.MC · SAN.MC · SOL.MC · TEF.MC · UNI.MC · VIS.MC`

---

## Indicadores regulatorios de riesgo

### SRRI — Indicador Sintético de Riesgo y Rendimiento (UCITS IV)

| Clase | Volatilidad anualizada | Perfil |
|:---:|---|---|
| 1 | < 0.5% | Fondos monetarios puros |
| 2 | 0.5% – 2% | Deuda soberana corto plazo |
| 3 | 2% – 5% | Renta fija investment grade |
| 4 | 5% – 10% | Mixtos defensivos globales |
| 5 | 10% – 15% | Renta variable baja volatilidad |
| **6** | **15% – 25%** | **Renta variable pura líquida** |
| 7 | ≥ 25% | Cíclicos, emergentes, materias primas |

### Semáforo CNMV (Orden ECC/2316/2015)

Las carteras compuestas íntegramente por acciones del Mercado Continuo español se clasifican obligatoriamente en el **Nivel 6/6**, advirtiendo de que no existe garantía de recuperación del capital invertido.

---

## Advertencia legal

Este software es una herramienta de apoyo a la toma de decisiones de inversión y **no constituye asesoramiento financiero**. Las instrucciones operativas generadas son orientativas y no garantizan resultados futuros. La inversión en renta variable conlleva riesgo de pérdida total del capital. Consulte con un asesor financiero regulado antes de tomar decisiones de inversión.
