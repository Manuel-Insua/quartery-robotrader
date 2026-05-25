"""
Módulo de presentación e informes.
Traduce los resultados cuantitativos en salidas comprensibles para el inversor
minorista, siguiendo los estándares regulatorios europeos UCITS y CNMV.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── SRRI UCITS IV ─────────────────────────────────────────────────────────────
# Límite superior de volatilidad anualizada para cada clase (1–7)
_SRRI_UPPER_BOUNDS: list[float] = [0.005, 0.02, 0.05, 0.10, 0.15, 0.25]

_SRRI_LABELS: dict[int, str] = {
    1: "Muy bajo      (fondos monetarios puros)",
    2: "Bajo          (deuda soberana corto plazo)",
    3: "Moderado-bajo (renta fija investment grade)",
    4: "Moderado      (mixtos defensivos globales)",
    5: "Moderado-alto (renta variable baja vol.)",
    6: "Alto          (renta variable pura líquida)",
    7: "Muy alto      (cíclicos, emergentes, materias primas)",
}


def compute_srri(annual_volatility: float) -> int:
    """
    Convierte la volatilidad anualizada al indicador SRRI (escala 1–7)
    según la Directiva UCITS IV y el documento KIID.
    """
    for srri_class, upper in enumerate(_SRRI_UPPER_BOUNDS, start=1):
        if annual_volatility < upper:
            return srri_class
    return 7


def _srri_gauge(srri: int) -> str:
    """Representación visual del nivel SRRI en barra de bloques."""
    bar = "█" * srri + "░" * (7 - srri)
    return f"[{bar}]  {srri}/7  —  {_SRRI_LABELS[srri]}"


@dataclass
class ReportData:
    nav: float
    capital_neto: float
    volatility: float
    target_weights: dict[str, float]
    orders: dict[str, int]
    current_positions: dict[str, int]
    prices: dict[str, float]
    metadata: dict


def print_report(data: ReportData) -> None:
    srri = compute_srri(data.volatility)
    divisa = data.metadata.get("divisa", "EUR")
    ultimo_rebalanceo = data.metadata.get("fecha_ultimo_rebalanceo", "N/D")

    W = 68
    sep_doble = "═" * W
    sep_simple = "─" * W

    # ═══════════════════════════════════════════════════════════════
    print(f"\n{sep_doble}")
    print(f"  {'OPTIMIZADOR GMVP — MERCADO CONTINUO ESPAÑOL':^{W-4}}")
    print(f"  {'Cartera de Mínima Varianza Global · Rebalanceo Trimestral':^{W-4}}")
    print(sep_doble)

    # ── RESUMEN FINANCIERO ─────────────────────────────────────────
    print(f"\n  {'RESUMEN FINANCIERO':^{W-4}}")
    print(f"  {sep_simple}")
    print(f"  {'Fecha último rebalanceo:':<36} {ultimo_rebalanceo:>{W-40}}")
    print(f"  {'Valor total (NAV):':<36} {data.nav:>{W-42},.2f}  {divisa}")
    print(f"  {'Efectivo neto disponible:':<36} {data.capital_neto:>{W-42},.2f}  {divisa}")

    # ── PERFIL DE RIESGO ───────────────────────────────────────────
    print(f"\n  {'PERFIL DE RIESGO POST-OPTIMIZACIÓN':^{W-4}}")
    print(f"  {sep_simple}")
    print(f"  {'Volatilidad anualizada (GMVP):':<36} {data.volatility * 100:>{W-42}.3f}  %")
    print(f"  {'SRRI (UCITS IV, Directiva KID):':<36}")
    print(f"    {_srri_gauge(srri)}")
    print(f"  {'Semáforo CNMV (Ord. ECC/2316/2015):':<36} {'Nivel 6 / 6':>{W-42}}")

    print(
        f"\n  {'─' * (W-4)}\n"
        f"  ⚠  ADVERTENCIA REGULATORIA CNMV:\n"
        f"     Esta cartera está compuesta íntegramente por renta variable\n"
        f"     española (Nivel 6). No existe garantía de recuperación del\n"
        f"     capital invertido. La inversión puede resultar en pérdida total."
    )

    # ── DISTRIBUCIÓN ÓPTIMA ────────────────────────────────────────
    print(f"\n  {'DISTRIBUCIÓN ÓPTIMA GMVP  (pesos ≥ 0.5 %)':^{W-4}}")
    print(f"  {sep_simple}")
    print(f"  {'Ticker':<10} {'Peso Óptimo':>12}  {'Capital (EUR)':>16}  {'Precio':>10}")
    print(f"  {'─'*10} {'─'*12}  {'─'*16}  {'─'*10}")

    active_weights = {
        t: w for t, w in data.target_weights.items() if w >= 0.005
    }
    for ticker, w in sorted(active_weights.items(), key=lambda x: x[1], reverse=True):
        capital = data.nav * w
        precio = data.prices.get(ticker, 0.0)
        print(f"  {ticker:<10} {w * 100:>11.2f}%  {capital:>16,.2f}  {precio:>10.2f}")

    n_active = len(active_weights)
    print(f"\n  Activos con asignación positiva: {n_active}  |  "
          f"Concentración máxima: {max(active_weights.values()) * 100:.1f}%")

    # ── INSTRUCCIONES OPERATIVAS ───────────────────────────────────
    buys = {t: d for t, d in data.orders.items() if d > 0}
    sells = {t: d for t, d in data.orders.items() if d < 0}

    print(f"\n  {'INSTRUCCIONES OPERATIVAS':^{W-4}}")
    print(f"  {sep_simple}")

    if not buys and not sells:
        print(
            "  ✓  Cartera dentro de las bandas de tolerancia (±5% abs / ±25% rel).\n"
            "     No se requiere ninguna operación en este ciclo trimestral."
        )
    else:
        print(f"  {'Operación':<10} {'Acciones':>10}  {'Ticker':<10} "
              f"{'Precio':>10}  {'Importe (EUR)':>16}")
        print(f"  {'─'*10} {'─'*10}  {'─'*10} {'─'*10}  {'─'*16}")

        for ticker, qty in sorted(buys.items(), key=lambda x: abs(x[1]), reverse=True):
            precio = data.prices.get(ticker, 0.0)
            importe = abs(qty) * precio
            print(f"  {'COMPRAR':<10} {abs(qty):>10}  {ticker:<10} "
                  f"{precio:>10.2f}  {importe:>16,.2f}")

        for ticker, qty in sorted(sells.items(), key=lambda x: abs(x[1]), reverse=True):
            precio = data.prices.get(ticker, 0.0)
            importe = abs(qty) * precio
            print(f"  {'VENDER':<10} {abs(qty):>10}  {ticker:<10} "
                  f"{precio:>10.2f}  {importe:>16,.2f}")

    # ── POSICIONES SIN CAMBIO ──────────────────────────────────────
    no_action = sorted(
        t for t in data.current_positions
        if t not in data.orders and data.current_positions[t] > 0
    )
    if no_action:
        print(f"\n  Posiciones dentro de banda (sin operación): {', '.join(no_action)}")

    print(f"\n{sep_doble}\n")
