import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from bot_engine import QueryEngine

@pytest.fixture(scope="module")
def engine():
    return QueryEngine(seed=42, n_rows=5000)

def _parse_number(text: str) -> float:
    import re
    nums = re.findall(r"[\d,]+\.?\d*", text.replace(",", ""))
    return float(nums[0]) if nums else 0.0

def test_q1_total_ventas(engine):
    result = engine.answer("total de ventas")
    assert "$" in result
    val = _parse_number(result.split("$")[-1])
    assert val > 0

def test_q2_ganancia_total(engine):
    result = engine.answer("ganancia total")
    assert "$" in result
    val = _parse_number(result.split("$")[-1])
    assert val > 0

def test_q3_margen(engine):
    result = engine.answer("margen de ganancia")
    assert "%" in result
    import re
    val = float(re.search(r"([\d.]+)%", result).group(1))
    assert 0 < val < 100

def test_q4_clientes_unicos(engine):
    result = engine.answer("clientes unicos")
    val = int(result.split(":")[-1].strip().replace(",", ""))
    assert val == 500

def test_q5_pedidos_totales(engine):
    result = engine.answer("pedidos totales")
    val = int(result.split(":")[-1].strip().replace(",", ""))
    assert val == 5000

def test_q6_categoria_mas_ventas(engine):
    result = engine.answer("ventas por categoria")
    assert any(c in result for c in ["Bikes", "Components", "Accessories"])

def test_q7_territorio_mas_ventas(engine):
    result = engine.answer("ventas por territorio")
    valid = ["Northwest","Northeast","Southwest","Southeast","Central",
             "France","Germany","Australia","Canada","United Kingdom"]
    assert any(r in result for r in valid)

def test_q8_unidades_vendidas(engine):
    result = engine.answer("unidades vendidas")
    val = int(result.split(":")[-1].strip().replace(",", ""))
    assert val > 0

def test_q9_promedio_por_pedido(engine):
    result = engine.answer("promedio por pedido")
    assert "$" in result
    val = _parse_number(result.split("$")[-1])
    assert val > 0

def test_q10_top_clientes(engine):
    result = engine.answer("top clientes")
    lines = [l for l in result.split("\n") if l.strip() and l[0].isdigit()]
    assert len(lines) == 3
