import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "control_total_pyme.db")

app = Flask(__name__)
app.secret_key = "cambia-esta-clave-en-produccion"


# ---------- Base de datos ----------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(force=False):
    nuevo = force or not os.path.exists(DB_PATH)
    conn = get_db()
    if nuevo:
        with open(os.path.join(BASE_DIR, "schema.sql"), "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        # Config inicial
        conn.execute("INSERT INTO config (clave, valor) VALUES ('pin_mostrador', '1234')")
        conn.execute("INSERT INTO config (clave, valor) VALUES ('nombre_negocio', 'Mi PyME')")
        # Usuario admin de ejemplo
        conn.execute(
            "INSERT INTO usuarios (nombre, email, password_hash, rol) VALUES (?, ?, ?, ?)",
            ("Administrador", "admin@pyme.com", generate_password_hash("admin123"), "admin"),
        )
        # Datos de ejemplo
        conn.executemany(
            "INSERT INTO productos (nombre, precio, costo, stock, stock_minimo) VALUES (?, ?, ?, ?, ?)",
            [
                ("Producto A", 1500, 900, 40, 10),
                ("Producto B", 800, 500, 15, 5),
                ("Producto C", 3200, 2000, 3, 5),
            ],
        )
        conn.executemany(
            "INSERT INTO costos_fijos (nombre, monto, periodicidad, tipo) VALUES (?, ?, ?, ?)",
            [
                ("Alquiler", 250000, "Mensual", "fijo"),
                ("Servicios (luz/agua/internet)", 60000, "Mensual", "fijo"),
                ("Sueldos", 400000, "Mensual", "fijo"),
            ],
        )
        conn.executemany(
            "INSERT INTO socios (nombre, porcentaje) VALUES (?, ?)",
            [("Socio 1", 60), ("Socio 2", 40)],
        )
        conn.commit()
    conn.close()


def registrar_historial(usuario, accion, detalle="", monto=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO historial (fecha, usuario, accion, detalle, monto) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), usuario, accion, detalle, monto),
    )
    conn.commit()
    conn.close()


def get_config(clave, default=None):
    conn = get_db()
    row = conn.execute("SELECT valor FROM config WHERE clave = ?", (clave,)).fetchone()
    conn.close()
    return row["valor"] if row else default


def set_config(clave, valor):
    conn = get_db()
    conn.execute(
        "INSERT INTO config (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        (clave, valor),
    )
    conn.commit()
    conn.close()


# ---------- Autenticación / control de acceso ----------
def login_required(roles=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if "rol" not in session:
                return redirect(url_for("acceso"))
            if roles and session["rol"] not in roles:
                flash("No tenés permisos para acceder a esa sección.", "error")
                return redirect(url_for("mostrador") if session["rol"] == "publico" else url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def inject_globals():
    return {
        "nombre_negocio": get_config("nombre_negocio", "Mi PyME"),
        "rol_actual": session.get("rol"),
        "usuario_actual": session.get("usuario_nombre", "Mostrador"),
    }


# ---------- Rutas de acceso ----------
@app.route("/")
def index():
    if "rol" in session:
        return redirect(url_for("mostrador") if session["rol"] == "publico" else url_for("dashboard"))
    return redirect(url_for("acceso"))


@app.route("/acceso")
def acceso():
    return render_template("acceso.html")


@app.route("/acceso/pin", methods=["GET", "POST"])
def acceso_pin():
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == get_config("pin_mostrador", "1234"):
            session.clear()
            session["rol"] = "publico"
            session["usuario_nombre"] = "Mostrador"
            return redirect(url_for("mostrador"))
        flash("PIN incorrecto.", "error")
    return render_template("acceso_pin.html")


@app.route("/acceso/admin", methods=["GET", "POST"])
def acceso_admin():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["rol"] = "privado"
            session["usuario_id"] = user["id"]
            session["usuario_nombre"] = user["nombre"]
            registrar_historial(user["nombre"], "Inicio de sesión (admin)")
            return redirect(url_for("dashboard"))
        flash("Email o contraseña incorrectos.", "error")
    return render_template("acceso_admin.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("acceso"))


# ---------- Mostrador (rol público) ----------
@app.route("/mostrador", methods=["GET", "POST"])
@login_required(roles=["publico", "privado"])
def mostrador():
    conn = get_db()
    if request.method == "POST":
        producto_id = int(request.form["producto_id"])
        cantidad = int(request.form["cantidad"])
        tipo_pago = request.form.get("tipo_pago", "Efectivo")
        producto = conn.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if not producto:
            flash("Producto no encontrado.", "error")
        elif producto["stock"] < cantidad:
            flash(f"Stock insuficiente de {producto['nombre']} (disponible: {producto['stock']}).", "error")
        else:
            total = producto["precio"] * cantidad
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur = conn.execute(
                "INSERT INTO ventas (fecha, total, usuario, tipo_pago) VALUES (?, ?, ?, ?)",
                (fecha, total, session.get("usuario_nombre"), tipo_pago),
            )
            venta_id = cur.lastrowid
            conn.execute(
                "INSERT INTO venta_items (venta_id, producto_id, producto_nombre, cantidad, precio_unitario) "
                "VALUES (?, ?, ?, ?, ?)",
                (venta_id, producto_id, producto["nombre"], cantidad, producto["precio"]),
            )
            conn.execute("UPDATE productos SET stock = stock - ? WHERE id = ?", (cantidad, producto_id))
            conn.execute(
                "INSERT INTO movimientos_caja (fecha, tipo, categoria, monto, descripcion) VALUES (?, 'ingreso', 'Venta', ?, ?)",
                (fecha, total, f"Venta ticket #{venta_id} - {producto['nombre']} x{cantidad}"),
            )
            conn.commit()
            registrar_historial(session.get("usuario_nombre"), "Venta registrada", f"{producto['nombre']} x{cantidad}", total)
            flash(f"Venta registrada. Ticket #{venta_id} - Total: ${total:,.2f}", "success")
            return redirect(url_for("ticket", venta_id=venta_id))

    productos = conn.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    conn.close()
    return render_template("mostrador.html", productos=productos)


@app.route("/ticket/<int:venta_id>")
@login_required(roles=["publico", "privado"])
def ticket(venta_id):
    conn = get_db()
    venta = conn.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    items = conn.execute("SELECT * FROM venta_items WHERE venta_id = ?", (venta_id,)).fetchall()
    conn.close()
    if not venta:
        flash("Ticket no encontrado.", "error")
        return redirect(url_for("mostrador"))
    return render_template("ticket.html", venta=venta, items=items)


# ---------- Dashboard (rol privado) ----------
@app.route("/dashboard")
@login_required(roles=["privado"])
def dashboard():
    conn = get_db()
    hoy = datetime.now()
    hace_7 = (hoy - timedelta(days=7)).strftime("%Y-%m-%d")
    hace_14 = (hoy - timedelta(days=14)).strftime("%Y-%m-%d")

    ventas_semana = conn.execute(
        "SELECT COALESCE(SUM(total),0) t, COUNT(*) c FROM ventas WHERE fecha >= ?", (hace_7,)
    ).fetchone()
    ventas_semana_prev = conn.execute(
        "SELECT COALESCE(SUM(total),0) t FROM ventas WHERE fecha >= ? AND fecha < ?", (hace_14, hace_7)
    ).fetchone()

    producto_top = conn.execute(
        "SELECT producto_nombre, SUM(cantidad) total_vendido FROM venta_items "
        "GROUP BY producto_nombre ORDER BY total_vendido DESC LIMIT 1"
    ).fetchone()

    ticket_promedio = (ventas_semana["t"] / ventas_semana["c"]) if ventas_semana["c"] else 0

    ingresos = conn.execute(
        "SELECT COALESCE(SUM(monto),0) FROM movimientos_caja WHERE tipo='ingreso'"
    ).fetchone()[0]
    egresos = conn.execute(
        "SELECT COALESCE(SUM(monto),0) FROM movimientos_caja WHERE tipo='egreso'"
    ).fetchone()[0]
    caja_disponible = ingresos - egresos

    # Ventas de los últimos 7 días para gráfico
    dias = []
    valores = []
    for i in range(6, -1, -1):
        dia = (hoy - timedelta(days=i)).strftime("%Y-%m-%d")
        total_dia = conn.execute(
            "SELECT COALESCE(SUM(total),0) FROM ventas WHERE fecha LIKE ?", (dia + "%",)
        ).fetchone()[0]
        dias.append((hoy - timedelta(days=i)).strftime("%d/%m"))
        valores.append(total_dia)

    stock_bajo = conn.execute(
        "SELECT * FROM productos WHERE stock <= stock_minimo ORDER BY stock ASC"
    ).fetchall()

    conn.close()

    variacion = 0
    if ventas_semana_prev["t"]:
        variacion = ((ventas_semana["t"] - ventas_semana_prev["t"]) / ventas_semana_prev["t"]) * 100

    return render_template(
        "dashboard.html",
        ventas_semana=ventas_semana["t"],
        variacion=round(variacion, 1),
        producto_top=producto_top["producto_nombre"] if producto_top else "Sin datos",
        ticket_promedio=ticket_promedio,
        caja_disponible=caja_disponible,
        dias=dias,
        valores=valores,
        stock_bajo=stock_bajo,
    )


# ---------- Estructura financiera (activos / pasivos) ----------
@app.route("/finanzas", methods=["GET", "POST"])
@login_required(roles=["privado"])
def finanzas():
    conn = get_db()
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "add_activo":
            conn.execute(
                "INSERT INTO activos (nombre, tipo, monto) VALUES (?, ?, ?)",
                (request.form["nombre"], request.form["tipo"], float(request.form["monto"])),
            )
            registrar_historial(session.get("usuario_nombre"), "Activo agregado", request.form["nombre"], float(request.form["monto"]))
        elif accion == "add_pasivo":
            conn.execute(
                "INSERT INTO pasivos (nombre, monto) VALUES (?, ?)",
                (request.form["nombre"], float(request.form["monto"])),
            )
            registrar_historial(session.get("usuario_nombre"), "Pasivo agregado", request.form["nombre"], float(request.form["monto"]))
        elif accion == "del_activo":
            conn.execute("DELETE FROM activos WHERE id = ?", (request.form["id"],))
        elif accion == "del_pasivo":
            conn.execute("DELETE FROM pasivos WHERE id = ?", (request.form["id"],))
        conn.commit()
        return redirect(url_for("finanzas"))

    activos = conn.execute("SELECT * FROM activos ORDER BY id DESC").fetchall()
    pasivos = conn.execute("SELECT * FROM pasivos ORDER BY id DESC").fetchall()
    total_activos = sum(a["monto"] for a in activos)
    total_pasivos = sum(p["monto"] for p in pasivos)
    patrimonio_neto = total_activos - total_pasivos
    conn.close()
    return render_template(
        "finanzas.html",
        activos=activos,
        pasivos=pasivos,
        total_activos=total_activos,
        total_pasivos=total_pasivos,
        patrimonio_neto=patrimonio_neto,
    )


# ---------- Flujo de caja ----------
@app.route("/flujo-caja", methods=["GET", "POST"])
@login_required(roles=["privado"])
def flujo_caja():
    conn = get_db()
    if request.method == "POST":
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tipo = request.form["tipo"]
        categoria = request.form["categoria"]
        monto = float(request.form["monto"])
        descripcion = request.form.get("descripcion", "")
        conn.execute(
            "INSERT INTO movimientos_caja (fecha, tipo, categoria, monto, descripcion) VALUES (?, ?, ?, ?, ?)",
            (fecha, tipo, categoria, monto, descripcion),
        )
        conn.commit()
        registrar_historial(session.get("usuario_nombre"), f"{tipo.capitalize()} de caja", f"{categoria}: {descripcion}", monto)
        return redirect(url_for("flujo_caja"))

    movimientos = conn.execute(
        "SELECT * FROM movimientos_caja ORDER BY fecha DESC LIMIT 100"
    ).fetchall()
    ingresos = conn.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos_caja WHERE tipo='ingreso'").fetchone()[0]
    egresos = conn.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos_caja WHERE tipo='egreso'").fetchone()[0]
    conn.close()
    return render_template(
        "flujo_caja.html", movimientos=movimientos, ingresos=ingresos, egresos=egresos, saldo=ingresos - egresos
    )


# ---------- Costos fijos y punto de equilibrio ----------
@app.route("/costos", methods=["GET", "POST"])
@login_required(roles=["privado"])
def costos():
    conn = get_db()
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "add":
            conn.execute(
                "INSERT INTO costos_fijos (nombre, monto, periodicidad, tipo) VALUES (?, ?, ?, ?)",
                (request.form["nombre"], float(request.form["monto"]), request.form["periodicidad"], request.form["tipo"]),
            )
        elif accion == "del":
            conn.execute("DELETE FROM costos_fijos WHERE id = ?", (request.form["id"],))
        conn.commit()
        return redirect(url_for("costos"))

    costos_fijos = conn.execute("SELECT * FROM costos_fijos WHERE tipo='fijo' ORDER BY id DESC").fetchall()
    costos_variables = conn.execute("SELECT * FROM costos_fijos WHERE tipo='variable' ORDER BY id DESC").fetchall()
    total_fijos = sum(c["monto"] for c in costos_fijos)
    total_variables = sum(c["monto"] for c in costos_variables)

    # Punto de equilibrio simplificado: usando margen de contribución promedio de productos
    productos = conn.execute("SELECT * FROM productos").fetchall()
    margen_promedio = 0
    if productos:
        margenes = [(p["precio"] - p["costo"]) for p in productos if p["precio"] > 0]
        margen_promedio = sum(margenes) / len(margenes) if margenes else 0
    punto_equilibrio_unidades = (total_fijos / margen_promedio) if margen_promedio > 0 else None
    conn.close()
    return render_template(
        "costos.html",
        costos_fijos=costos_fijos,
        costos_variables=costos_variables,
        total_fijos=total_fijos,
        total_variables=total_variables,
        margen_promedio=margen_promedio,
        punto_equilibrio_unidades=punto_equilibrio_unidades,
    )


# ---------- Stock ----------
@app.route("/stock", methods=["GET", "POST"])
@login_required(roles=["privado"])
def stock():
    conn = get_db()
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "add":
            conn.execute(
                "INSERT INTO productos (nombre, precio, costo, stock, stock_minimo) VALUES (?, ?, ?, ?, ?)",
                (
                    request.form["nombre"],
                    float(request.form["precio"]),
                    float(request.form["costo"]),
                    int(request.form["stock"]),
                    int(request.form["stock_minimo"]),
                ),
            )
            registrar_historial(session.get("usuario_nombre"), "Producto agregado", request.form["nombre"])
        elif accion == "ajustar":
            conn.execute(
                "UPDATE productos SET stock = ? WHERE id = ?",
                (int(request.form["nuevo_stock"]), request.form["id"]),
            )
            registrar_historial(session.get("usuario_nombre"), "Ajuste de stock", f"Producto ID {request.form['id']}")
        elif accion == "del":
            conn.execute("DELETE FROM productos WHERE id = ?", (request.form["id"],))
        conn.commit()
        return redirect(url_for("stock"))

    productos = conn.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    valor_stock = sum(p["costo"] * p["stock"] for p in productos)
    conn.close()
    return render_template("stock.html", productos=productos, valor_stock=valor_stock)


# ---------- Socios / CapTable ----------
@app.route("/socios", methods=["GET", "POST"])
@login_required(roles=["privado"])
def socios():
    conn = get_db()
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "add":
            conn.execute(
                "INSERT INTO socios (nombre, porcentaje) VALUES (?, ?)",
                (request.form["nombre"], float(request.form["porcentaje"])),
            )
        elif accion == "del":
            conn.execute("DELETE FROM socios WHERE id = ?", (request.form["id"],))
        conn.commit()
        return redirect(url_for("socios"))

    lista_socios = conn.execute("SELECT * FROM socios ORDER BY porcentaje DESC").fetchall()
    total_porcentaje = sum(s["porcentaje"] for s in lista_socios)

    ingresos = conn.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos_caja WHERE tipo='ingreso'").fetchone()[0]
    egresos = conn.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos_caja WHERE tipo='egreso'").fetchone()[0]
    ganancia_neta = ingresos - egresos
    conn.close()

    distribucion = [
        {"nombre": s["nombre"], "porcentaje": s["porcentaje"], "monto": ganancia_neta * (s["porcentaje"] / 100)}
        for s in lista_socios
    ]

    return render_template(
        "socios.html",
        socios=lista_socios,
        total_porcentaje=total_porcentaje,
        ganancia_neta=ganancia_neta,
        distribucion=distribucion,
    )


# ---------- Historial / Auditoría ----------
@app.route("/historial")
@login_required(roles=["privado"])
def historial():
    conn = get_db()
    registros = conn.execute("SELECT * FROM historial ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    return render_template("historial.html", registros=registros)


# ---------- Cierre mensual ----------
@app.route("/cierre-mensual", methods=["GET", "POST"])
@login_required(roles=["privado"])
def cierre_mensual():
    conn = get_db()
    if request.method == "POST":
        periodo = datetime.now().strftime("%Y-%m")
        ingresos = conn.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos_caja WHERE tipo='ingreso'").fetchone()[0]
        egresos = conn.execute("SELECT COALESCE(SUM(monto),0) FROM movimientos_caja WHERE tipo='egreso'").fetchone()[0]
        ganancia = ingresos - egresos
        conn.execute(
            "INSERT INTO cierres_mensuales (periodo, ingresos_totales, egresos_totales, ganancia_neta, fecha_cierre) "
            "VALUES (?, ?, ?, ?, ?)",
            (periodo, ingresos, egresos, ganancia, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        registrar_historial(session.get("usuario_nombre"), "Cierre mensual generado", periodo, ganancia)
        flash(f"Cierre del período {periodo} generado correctamente.", "success")
        return redirect(url_for("cierre_mensual"))

    cierres = conn.execute("SELECT * FROM cierres_mensuales ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("cierre_mensual.html", cierres=cierres)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
