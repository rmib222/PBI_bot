import os
import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
SEED = int(os.getenv("RANDOM_SEED", 42))
N_ROWS = int(os.getenv("SYNTHETIC_ROWS", 5000))


def generate_synthetic_data(seed: int = SEED, n_rows: int = N_ROWS) -> dict:
    rng = np.random.default_rng(seed)

    n_customers = 500
    customers = {
        "CustomerKey": list(range(1, n_customers + 1)),
        "Customer": [f"Customer_{i:04d}" for i in range(1, n_customers + 1)],
        "City": rng.choice(["Seattle", "Denver", "Portland", "Chicago", "Miami"], n_customers).tolist(),
        "Country-Region": rng.choice(["United States", "Canada", "United Kingdom"], n_customers).tolist(),
    }

    n_products = 200
    categories = rng.choice(["Bikes", "Components", "Accessories"], n_products).tolist()
    products = {
        "ProductKey": list(range(1, n_products + 1)),
        "Product": [f"Product_{i:04d}" for i in range(1, n_products + 1)],
        "Category": categories,
        "Subcategory": [f"Sub_{c[:3]}_{i % 5}" for i, c in enumerate(categories)],
        "List Price": rng.uniform(10, 3000, n_products).tolist(),
        "Standard Cost": rng.uniform(5, 1500, n_products).tolist(),
    }

    n_resellers = 50
    resellers = {
        "ResellerKey": list(range(1, n_resellers + 1)),
        "Reseller": [f"Reseller_{i:03d}" for i in range(1, n_resellers + 1)],
        "Business Type": rng.choice(["Specialty Bike Shop", "Value Added Reseller", "Warehouse"], n_resellers).tolist(),
        "Country-Region": rng.choice(["United States", "Canada", "Australia"], n_resellers).tolist(),
    }

    territories = {
        "SalesTerritoryKey": list(range(1, 11)),
        "Region": ["Northwest", "Northeast", "Southwest", "Southeast", "Central",
                   "France", "Germany", "Australia", "Canada", "United Kingdom"],
        "Country": ["United States"] * 5 + ["France", "Germany", "Australia", "Canada", "United Kingdom"],
        "Group": ["North America"] * 5 + ["Europe", "Europe", "Pacific", "North America", "Europe"],
    }

    sales_amounts = rng.uniform(50, 5000, n_rows)
    costs = sales_amounts * rng.uniform(0.4, 0.8, n_rows)
    sales = {
        "SalesOrderLineKey": list(range(1, n_rows + 1)),
        "CustomerKey": rng.integers(1, n_customers + 1, n_rows).tolist(),
        "ProductKey": rng.integers(1, n_products + 1, n_rows).tolist(),
        "ResellerKey": rng.integers(1, n_resellers + 1, n_rows).tolist(),
        "SalesTerritoryKey": rng.integers(1, 11, n_rows).tolist(),
        "Order Quantity": rng.integers(1, 20, n_rows).tolist(),
        "Unit Price": (sales_amounts / rng.integers(1, 10, n_rows)).tolist(),
        "Total Product Cost": costs.tolist(),
        "Sales Amount": sales_amounts.tolist(),
    }

    return {"sales": sales, "customer": customers, "product": products,
            "reseller": resellers, "sales_territory": territories}


class QueryEngine:
    def __init__(self, seed: int = SEED, n_rows: int = N_ROWS):
        self.conn = duckdb.connect(":memory:")
        data = generate_synthetic_data(seed, n_rows)
        for name, d in data.items():
            df = pd.DataFrame(d)
            self.conn.register(name, df)

    def _exec(self, sql: str):
        return self.conn.execute(sql)

    def answer(self, question: str) -> str:
        q = question.lower().strip()

        if any(w in q for w in ["total de ventas", "ventas totales", "revenue", "ingresos"]):
            val = self._exec('SELECT SUM("Sales Amount") FROM sales').fetchone()[0]
            return f"Total de Ventas: ${val:,.0f}"

        if any(w in q for w in ["ganancia total", "profit", "beneficio", "ganancias"]):
            val = self._exec('SELECT SUM("Sales Amount") - SUM("Total Product Cost") FROM sales').fetchone()[0]
            return f"Ganancia Total: ${val:,.0f}"

        if any(w in q for w in ["margen", "margin", "rentabilidad"]):
            val = self._exec(
                'SELECT (SUM("Sales Amount") - SUM("Total Product Cost")) / SUM("Sales Amount") * 100 FROM sales'
            ).fetchone()[0]
            return f"Margen de Ganancia: {val:.1f}%"

        if any(w in q for w in ["clientes unicos", "clientes únicos", "cuantos clientes", "numero de clientes"]):
            val = self._exec('SELECT COUNT(DISTINCT "CustomerKey") FROM sales').fetchone()[0]
            return f"Clientes Unicos: {val:,}"

        if any(w in q for w in ["pedidos", "orders", "ordenes"]):
            val = self._exec('SELECT COUNT(DISTINCT "SalesOrderLineKey") FROM sales').fetchone()[0]
            return f"Total Pedidos: {val:,}"

        if any(w in q for w in ["categoria", "category"]):
            rows = self._exec(
                'SELECT p.Category, SUM(s."Sales Amount") AS total '
                'FROM sales s JOIN product p ON s."ProductKey" = p."ProductKey" '
                'GROUP BY p.Category ORDER BY total DESC'
            ).fetchall()
            lines = [f"{i+1}. {r[0]} - ${r[1]:,.0f}" for i, r in enumerate(rows)]
            return "Ventas por Categoria:\n" + "\n".join(lines)

        if any(w in q for w in ["territorio", "region"]):
            rows = self._exec(
                'SELECT st.Region, SUM(s."Sales Amount") AS total '
                'FROM sales s JOIN sales_territory st ON s."SalesTerritoryKey" = st."SalesTerritoryKey" '
                'GROUP BY st.Region ORDER BY total DESC'
            ).fetchall()
            lines = [f"{i+1}. {r[0]} - ${r[1]:,.0f}" for i, r in enumerate(rows)]
            return "Ventas por Territorio:\n" + "\n".join(lines)

        if any(w in q for w in ["unidades", "units", "cantidad vendida"]):
            val = self._exec('SELECT SUM("Order Quantity") FROM sales').fetchone()[0]
            return f"Unidades Vendidas: {val:,}"

        if any(w in q for w in ["promedio por pedido", "average order", "ticket promedio"]):
            val = self._exec(
                'SELECT SUM("Sales Amount") / COUNT(DISTINCT "SalesOrderLineKey") FROM sales'
            ).fetchone()[0]
            return f"Promedio por Pedido: ${val:,.2f}"

        if any(w in q for w in ["top", "mejores clientes", "top clientes"]):
            rows = self._exec(
                'SELECT c.Customer, SUM(s."Sales Amount") AS total '
                'FROM sales s JOIN customer c ON s."CustomerKey" = c."CustomerKey" '
                'GROUP BY c.Customer ORDER BY total DESC LIMIT 3'
            ).fetchall()
            lines = [f"{i+1}. {r[0]} - ${r[1]:,.0f}" for i, r in enumerate(rows)]
            return "Top 3 Clientes:\n" + "\n".join(lines)

        raise ValueError(f"Pregunta no reconocida: {question}")

    def help_text(self) -> str:
        return (
            "Preguntas disponibles:\n"
            "- total de ventas\n"
            "- ganancia total\n"
            "- margen de ganancia\n"
            "- clientes unicos\n"
            "- pedidos totales\n"
            "- ventas por categoria\n"
            "- ventas por territorio\n"
            "- unidades vendidas\n"
            "- promedio por pedido\n"
            "- top clientes"
        )


if __name__ == "__main__":
    engine = QueryEngine()
    for q in ["total de ventas", "ganancia total", "margen de ganancia", "clientes unicos",
              "pedidos totales", "ventas por categoria", "ventas por territorio",
              "unidades vendidas", "promedio por pedido", "top clientes"]:
        print(f"\n[{q}]\n{engine.answer(q)}")
