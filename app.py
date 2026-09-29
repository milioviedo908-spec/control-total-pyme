import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import wraps
import psycopg2
import psycopg2.extras
import psycopg2.pool
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL")  # URL de conexión de Neon
ZONA_HORARIA = ZoneInfo(os.environ.get("TZ_NEGOCIO", "America/Argentina/Cordoba"))


def ahora():
    """Fecha y hora actual en la zona horaria del negocio (el servidor corre en UTC)."""
    return datetime.now(ZONA_HORARIA)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")


# ---------- Base de datos (PostgreSQL / Neon) ----------
# Pool de conexiones: en vez de abrir una conexión nueva (con su handshake SSL contra
# Neon) en cada página, se reutilizan conexiones ya abiertas. Esto es lo que hace que
# cambiar de sección se sienta mucho más rápido.
_pool = None


def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "Falta la variable de entorno DATABASE_URL con la cadena de conexión de Neon."
            )
        _pool = psycopg2.pool.ThreadedConnectionPool(
            1, 10,
            DATABASE_URL,
            sslmode="require",
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _pool


def get_db():
    return get_pool().getconn()


def release_db(conn):
    """Devuelve la conexión al pool en vez de cerrarla de verdad."""
    if conn is not None:
        try:
            get_pool().putconn(conn)
        except Exception:
            pass


def conn_execute(conn, sql, params=()):
    """Ejecuta una consulta y devuelve el cursor (equivalente a conn.execute de sqlite3)."""
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def init_db(force=False):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'usuarios')"
    )
    existe = cur.fetchone()["exists"]
    if force or not existe:
        with open(os.path.join(BASE_DIR, "schema.sql"), "r", encoding="utf-8") as f:
            cur.execute(f.read())
        cur.execute("INSERT INTO config (clave, valor) VALUES ('pin_mostrador', '1234')")
        cur.execute("INSERT INTO config (clave, valor) VALUES ('nombre_negocio', 'Mi PyME')")
        cur.execute(
            "INSERT INTO usuarios (nombre, email, password_hash, rol) VALUES (%s, %s, %s, %s)",
            ("Administrador", "admin@pyme.com", generate_password_hash("admin123"), "admin"),
        )
        cur.executemany(
            "INSERT INTO productos (nombre, precio, costo, stock, stock_minimo) VALUES (%s, %s, %s, %s, %s)",
            [
                ("Producto A", 1500, 900, 40, 10),
                ("Producto B", 800, 500, 15, 5),
                ("Producto C", 3200, 2000, 3, 5),
            ],
        )
        cur.executemany(
            "INSERT INTO costos_fijos (nombre, monto, periodicidad, tipo) VALUES (%s, %s, %s, %s)",
            [
                ("Alquiler", 250000, "Mensual", "fijo"),
                ("Servicios (luz/agua/internet)", 60000, "Mensual", "fijo"),
                ("Sueldos", 400000, "Mensual", "fijo"),
            ],
        )
        # Los socios arrancan vacíos: se cargan desde la sección "Socios" cuando corresponda.
        conn.commit()

    # Migración: agrega columnas nuevas a bases ya existentes sin perder datos.
    columnas_nuevas = [
        "total_activos NUMERIC(12,2)",
        "total_pasivos NUMERIC(12,2)",
        "patrimonio_neto NUMERIC(12,2)",
        "total_costos_fijos NUMERIC(12,2)",
        "total_costos_variables NUMERIC(12,2)",
        "valor_stock NUMERIC(12,2)",
    ]
    for columna in columnas_nuevas:
        nombre_col = columna.split()[0]
        cur.execute(f"ALTER TABLE cierres_mensuales ADD COLUMN IF NOT EXISTS {columna}")
    cur.execute("ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS costo_unitario NUMERIC(12,2)")
    conn.commit()

    cur.close()
    release_db(conn)


def registrar_historial(usuario, accion, detalle="", monto=None):
    conn = get_db()
    conn_execute(
        conn,
        "INSERT INTO historial (fecha, usuario, accion, detalle, monto) VALUES (%s, %s, %s, %s, %s)",
        (ahora().strftime("%Y-%m-%d %H:%M:%S"), usuario, accion, detalle, monto),
    )
    conn.commit()
    release_db(conn)


def get_config(clave, default=None):
    conn = get_db()
    row = conn_execute(conn, "SELECT valor FROM config WHERE clave = %s", (clave,)).fetchone()
    release_db(conn)
    return row["valor"] if row else default


def set_config(clave, valor):
    conn = get_db()
    conn_execute(
        conn,
        "INSERT INTO config (clave, valor) VALUES (%s, %s) "
        "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
        (clave, valor),
    )
    conn.commit()
    release_db(conn)


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
        user = conn_execute(conn, "SELECT * FROM usuarios WHERE email = %s", (email,)).fetchone()
        release_db(conn)
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
        producto = conn_execute(conn, "SELECT * FROM productos WHERE id = %s", (producto_id,)).fetchone()
        if not producto:
            flash("Producto no encontrado.", "error")
        elif producto["stock"] < cantidad:
            flash(f"Stock insuficiente de {producto['nombre']} (disponible: {producto['stock']}).", "error")
        else:
            total = float(producto["precio"]) * cantidad
            fecha = ahora().strftime("%Y-%m-%d %H:%M:%S")
            venta_id = conn_execute(
                conn,
                "INSERT INTO ventas (fecha, total, usuario, tipo_pago) VALUES (%s, %s, %s, %s) RETURNING id",
                (fecha, total, session.get("usuario_nombre"), tipo_pago),
            ).fetchone()["id"]
            conn_execute(
                conn,
                "INSERT INTO venta_items (venta_id, producto_id, producto_nombre, cantidad, precio_unitario, costo_unitario) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (venta_id, producto_id, producto["nombre"], cantidad, producto["precio"], producto["costo"]),
            )
            conn_execute(conn, "UPDATE productos SET stock = stock - %s WHERE id = %s", (cantidad, producto_id))
            conn_execute(
                conn,
                "INSERT INTO movimientos_caja (fecha, tipo, categoria, monto, descripcion) "
                "VALUES (%s, 'ingreso', 'Venta', %s, %s)",
                (fecha, total, f"Venta ticket #{venta_id} - {producto['nombre']} x{cantidad}"),
            )
            conn.commit()
            release_db(conn)
            registrar_historial(session.get("usuario_nombre"), "Venta registrada", f"{producto['nombre']} x{cantidad}", total)
            flash(f"Venta registrada. Ticket #{venta_id} - Total: ${total:,.2f}", "success")
            return redirect(url_for("ticket", venta_id=venta_id))

    productos = conn_execute(conn, "SELECT * FROM productos ORDER BY nombre").fetchall()
    release_db(conn)
    return render_template("mostrador.html", productos=productos)


@app.route("/ticket/<int:venta_id>")
@login_required(roles=["publico", "privado"])
def ticket(venta_id):
    conn = get_db()
    venta = conn_execute(conn, "SELECT * FROM ventas WHERE id = %s", (venta_id,)).fetchone()
    items = conn_execute(conn, "SELECT * FROM venta_items WHERE venta_id = %s", (venta_id,)).fetchall()
    release_db(conn)
    if not venta:
        flash("Ticket no encontrado.", "error")
        return redirect(url_for("mostrador"))
    return render_template("ticket.html", venta=venta, items=items)


# ---------- Dashboard (rol privado) ----------
@app.route("/dashboard")
@login_required(roles=["privado"])
def dashboard():
    conn = get_db()
    hoy = ahora()
    hace_7 = (hoy - timedelta(days=7)).strftime("%Y-%m-%d")
    hace_14 = (hoy - timedelta(days=14)).strftime("%Y-%m-%d")

    ventas_semana = conn_execute(
        conn, "SELECT COALESCE(SUM(total),0) t, COUNT(*) c FROM ventas WHERE fecha >= %s", (hace_7,)
    ).fetchone()
    ventas_semana_prev = conn_execute(
        conn, "SELECT COALESCE(SUM(total),0) t FROM ventas WHERE fecha >= %s AND fecha < %s", (hace_14, hace_7)
    ).fetchone()

    producto_top = conn_execute(
        conn,
        "SELECT producto_nombre, SUM(cantidad) total_vendido FROM venta_items "
        "GROUP BY producto_nombre ORDER BY total_vendido DESC LIMIT 1",
    ).fetchone()

    ventas_semana_t = float(ventas_semana["t"])
    ticket_promedio = (ventas_semana_t / ventas_semana["c"]) if ventas_semana["c"] else 0

    ingresos = float(conn_execute(
        conn, "SELECT COALESCE(SUM(monto),0) AS s FROM movimientos_caja WHERE tipo='ingreso'"
    ).fetchone()["s"])
    egresos = float(conn_execute(
        conn, "SELECT COALESCE(SUM(monto),0) AS s FROM movimientos_caja WHERE tipo='egreso'"
    ).fetchone()["s"])
    caja_disponible = ingresos - egresos

    dias = []
    valores = []
    for i in range(6, -1, -1):
        dia = (hoy - timedelta(days=i)).strftime("%Y-%m-%d")
        total_dia = conn_execute(
            conn, "SELECT COALESCE(SUM(total),0) AS s FROM ventas WHERE fecha LIKE %s", (dia + "%",)
        ).fetchone()["s"]
        dias.append((hoy - timedelta(days=i)).strftime("%d/%m"))
        valores.append(float(total_dia))

    stock_bajo = conn_execute(
        conn, "SELECT * FROM productos WHERE stock <= stock_minimo ORDER BY stock ASC"
    ).fetchall()

    # Ganancia real de lo vendido: (precio - costo al momento de la venta) x cantidad.
    # Solo cuenta ventas hechas después de agregar esta función (tienen costo_unitario guardado).
    ganancia_vendido = conn_execute(
        conn,
        "SELECT COALESCE(SUM((precio_unitario - costo_unitario) * cantidad), 0) AS s "
        "FROM venta_items WHERE costo_unitario IS NOT NULL",
    ).fetchone()["s"]
    facturacion_bruta = conn_execute(
        conn, "SELECT COALESCE(SUM(precio_unitario * cantidad), 0) AS s FROM venta_items WHERE costo_unitario IS NOT NULL"
    ).fetchone()["s"]
    hay_ventas_sin_costo = conn_execute(
        conn, "SELECT COUNT(*) AS c FROM venta_items WHERE costo_unitario IS NULL"
    ).fetchone()["c"] > 0

    release_db(conn)

    variacion = 0
    prev_t = float(ventas_semana_prev["t"])
    if prev_t:
        variacion = ((ventas_semana_t - prev_t) / prev_t) * 100

    return render_template(
        "dashboard.html",
        ventas_semana=ventas_semana_t,
        variacion=round(variacion, 1),
        producto_top=producto_top["producto_nombre"] if producto_top else "Sin datos",
        ticket_promedio=ticket_promedio,
        caja_disponible=caja_disponible,
        ganancia_vendido=float(ganancia_vendido),
        facturacion_bruta=float(facturacion_bruta),
        hay_ventas_sin_costo=hay_ventas_sin_costo,
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
            conn_execute(
                conn,
                "INSERT INTO activos (nombre, tipo, monto) VALUES (%s, %s, %s)",
                (request.form["nombre"], request.form["tipo"], float(request.form["monto"])),
            )
            registrar_historial(session.get("usuario_nombre"), "Activo agregado", request.form["nombre"], float(request.form["monto"]))
        elif accion == "add_pasivo":
            conn_execute(
                conn,
                "INSERT INTO pasivos (nombre, monto) VALUES (%s, %s)",
                (request.form["nombre"], float(request.form["monto"])),
            )
            registrar_historial(session.get("usuario_nombre"), "Pasivo agregado", request.form["nombre"], float(request.form["monto"]))
        elif accion == "del_activo":
            conn_execute(conn, "DELETE FROM activos WHERE id = %s", (int(request.form["id"]),))
        elif accion == "del_pasivo":
            conn_execute(conn, "DELETE FROM pasivos WHERE id = %s", (int(request.form["id"]),))
        conn.commit()
        release_db(conn)
        return redirect(url_for("finanzas"))

    activos = conn_execute(conn, "SELECT * FROM activos ORDER BY id DESC").fetchall()
    pasivos = conn_execute(conn, "SELECT * FROM pasivos ORDER BY id DESC").fetchall()
    total_activos = sum(float(a["monto"]) for a in activos)
    total_pasivos = sum(float(p["monto"]) for p in pasivos)
    patrimonio_neto = total_activos - total_pasivos
    release_db(conn)
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
        fecha = ahora().strftime("%Y-%m-%d %H:%M:%S")
        tipo = request.form["tipo"]
        categoria = request.form["categoria"]
        monto = float(request.form["monto"])
        descripcion = request.form.get("descripcion", "")
        conn_execute(
            conn,
            "INSERT INTO movimientos_caja (fecha, tipo, categoria, monto, descripcion) VALUES (%s, %s, %s, %s, %s)",
            (fecha, tipo, categoria, monto, descripcion),
        )
        conn.commit()
        release_db(conn)
        registrar_historial(session.get("usuario_nombre"), f"{tipo.capitalize()} de caja", f"{categoria}: {descripcion}", monto)
        return redirect(url_for("flujo_caja"))

    movimientos = conn_execute(
        conn, "SELECT * FROM movimientos_caja ORDER BY fecha DESC LIMIT 100"
    ).fetchall()
    ingresos = float(conn_execute(conn, "SELECT COALESCE(SUM(monto),0) AS s FROM movimientos_caja WHERE tipo='ingreso'").fetchone()["s"])
    egresos = float(conn_execute(conn, "SELECT COALESCE(SUM(monto),0) AS s FROM movimientos_caja WHERE tipo='egreso'").fetchone()["s"])
    release_db(conn)
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
            conn_execute(
                conn,
                "INSERT INTO costos_fijos (nombre, monto, periodicidad, tipo) VALUES (%s, %s, %s, %s)",
                (request.form["nombre"], float(request.form["monto"]), request.form["periodicidad"], request.form["tipo"]),
            )
        elif accion == "del":
            conn_execute(conn, "DELETE FROM costos_fijos WHERE id = %s", (int(request.form["id"]),))
        conn.commit()
        release_db(conn)
        return redirect(url_for("costos"))

    costos_fijos = conn_execute(conn, "SELECT * FROM costos_fijos WHERE tipo='fijo' ORDER BY id DESC").fetchall()
    costos_variables = conn_execute(conn, "SELECT * FROM costos_fijos WHERE tipo='variable' ORDER BY id DESC").fetchall()
    total_fijos = sum(float(c["monto"]) for c in costos_fijos)
    total_variables = sum(float(c["monto"]) for c in costos_variables)

    productos = conn_execute(conn, "SELECT * FROM productos").fetchall()
    margen_promedio = 0
    if productos:
        margenes = [(float(p["precio"]) - float(p["costo"])) for p in productos if p["precio"] > 0]
        margen_promedio = sum(margenes) / len(margenes) if margenes else 0
    punto_equilibrio_unidades = (total_fijos / margen_promedio) if margen_promedio > 0 else None
    release_db(conn)
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
            conn_execute(
                conn,
                "INSERT INTO productos (nombre, precio, costo, stock, stock_minimo) VALUES (%s, %s, %s, %s, %s)",
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
            conn_execute(
                conn,
                "UPDATE productos SET stock = %s, precio = %s, costo = %s WHERE id = %s",
                (
                    int(request.form["nuevo_stock"]),
                    float(request.form["nuevo_precio"]),
                    float(request.form["nuevo_costo"]),
                    int(request.form["id"]),
                ),
            )
            registrar_historial(session.get("usuario_nombre"), "Producto actualizado", f"Producto ID {request.form['id']}")
        elif accion == "del":
            try:
                conn_execute(conn, "DELETE FROM productos WHERE id = %s", (int(request.form["id"]),))
                conn.commit()
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()
                flash(
                    "No se puede eliminar este producto porque ya tiene ventas registradas. "
                    "Si no lo vendés más, poné su stock en 0 en lugar de borrarlo.",
                    "error",
                )
            release_db(conn)
            return redirect(url_for("stock"))
        conn.commit()
        release_db(conn)
        return redirect(url_for("stock"))

    productos = conn_execute(conn, "SELECT * FROM productos ORDER BY nombre").fetchall()
    valor_stock = sum(float(p["costo"]) * p["stock"] for p in productos)
    ganancia_potencial = sum((float(p["precio"]) - float(p["costo"])) * p["stock"] for p in productos)
    release_db(conn)
    return render_template(
        "stock.html", productos=productos, valor_stock=valor_stock, ganancia_potencial=ganancia_potencial
    )


# ---------- Socios / CapTable ----------
@app.route("/socios", methods=["GET", "POST"])
@login_required(roles=["privado"])
def socios():
    conn = get_db()
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "add":
            nuevo_porcentaje = float(request.form["porcentaje"])
            total_actual = float(
                conn_execute(conn, "SELECT COALESCE(SUM(porcentaje),0) AS s FROM socios").fetchone()["s"]
            )
            if total_actual + nuevo_porcentaje > 100:
                disponible = 100 - total_actual
                flash(
                    f"No se puede agregar ese porcentaje: ya hay {total_actual:.2f}% asignado. "
                    f"Como máximo podés cargar {disponible:.2f}% más.",
                    "error",
                )
            else:
                conn_execute(
                    conn,
                    "INSERT INTO socios (nombre, porcentaje) VALUES (%s, %s)",
                    (request.form["nombre"], nuevo_porcentaje),
                )
        elif accion == "del":
            conn_execute(conn, "DELETE FROM socios WHERE id = %s", (int(request.form["id"]),))
        conn.commit()
        release_db(conn)
        return redirect(url_for("socios"))

    lista_socios = conn_execute(conn, "SELECT * FROM socios ORDER BY porcentaje DESC").fetchall()
    total_porcentaje = sum(float(s["porcentaje"]) for s in lista_socios)

    ingresos = float(conn_execute(conn, "SELECT COALESCE(SUM(monto),0) AS s FROM movimientos_caja WHERE tipo='ingreso'").fetchone()["s"])
    egresos = float(conn_execute(conn, "SELECT COALESCE(SUM(monto),0) AS s FROM movimientos_caja WHERE tipo='egreso'").fetchone()["s"])
    ganancia_neta = ingresos - egresos
    release_db(conn)

    distribucion = [
        {"nombre": s["nombre"], "porcentaje": float(s["porcentaje"]), "monto": ganancia_neta * (float(s["porcentaje"]) / 100)}
        for s in lista_socios
    ]

    return render_template(
        "socios.html",
        socios=lista_socios,
        total_porcentaje=total_porcentaje,
        ganancia_neta=ganancia_neta,
        distribucion=distribucion,
    )


# ---------- Facturación por producto ----------
@app.route("/facturacion")
@login_required(roles=["privado"])
def facturacion():
    conn = get_db()
    filas = conn_execute(
        conn,
        "SELECT producto_nombre, "
        "SUM(cantidad) AS unidades, "
        "SUM(precio_unitario * cantidad) AS facturado, "
        "SUM(CASE WHEN costo_unitario IS NOT NULL THEN costo_unitario * cantidad ELSE 0 END) AS costo, "
        "SUM(CASE WHEN costo_unitario IS NULL THEN cantidad ELSE 0 END) AS unidades_sin_costo "
        "FROM venta_items "
        "GROUP BY producto_nombre "
        "ORDER BY facturado DESC",
    ).fetchall()

    filas_calculadas = []
    total_facturado = 0.0
    total_costo = 0.0
    hay_faltantes = False
    for f in filas:
        facturado = float(f["facturado"])
        costo = float(f["costo"])
        ganancia = facturado - costo
        total_facturado += facturado
        total_costo += costo
        if f["unidades_sin_costo"] > 0:
            hay_faltantes = True
        filas_calculadas.append({
            "producto_nombre": f["producto_nombre"],
            "unidades": f["unidades"],
            "facturado": facturado,
            "costo": costo,
            "ganancia": ganancia,
            "unidades_sin_costo": f["unidades_sin_costo"],
        })

    release_db(conn)
    return render_template(
        "facturacion.html",
        filas=filas_calculadas,
        total_facturado=total_facturado,
        total_costo=total_costo,
        total_ganancia=total_facturado - total_costo,
        hay_faltantes=hay_faltantes,
    )


# ---------- Historial / Auditoría ----------
@app.route("/historial")
@login_required(roles=["privado"])
def historial():
    conn = get_db()
    registros = conn_execute(conn, "SELECT * FROM historial ORDER BY id DESC LIMIT 200").fetchall()
    release_db(conn)
    return render_template("historial.html", registros=registros)


# ---------- Cierre mensual ----------
@app.route("/cierre-mensual", methods=["GET", "POST"])
@login_required(roles=["privado"])
def cierre_mensual():
    conn = get_db()
    if request.method == "POST":
        periodo = ahora().strftime("%Y-%m")

        ingresos = float(conn_execute(conn, "SELECT COALESCE(SUM(monto),0) AS s FROM movimientos_caja WHERE tipo='ingreso'").fetchone()["s"])
        egresos = float(conn_execute(conn, "SELECT COALESCE(SUM(monto),0) AS s FROM movimientos_caja WHERE tipo='egreso'").fetchone()["s"])
        ganancia = ingresos - egresos

        activos = conn_execute(conn, "SELECT * FROM activos").fetchall()
        pasivos = conn_execute(conn, "SELECT * FROM pasivos").fetchall()
        total_activos = sum(float(a["monto"]) for a in activos)
        total_pasivos = sum(float(p["monto"]) for p in pasivos)
        patrimonio_neto = total_activos - total_pasivos

        costos = conn_execute(conn, "SELECT * FROM costos_fijos").fetchall()
        total_costos_fijos = sum(float(c["monto"]) for c in costos if c["tipo"] == "fijo")
        total_costos_variables = sum(float(c["monto"]) for c in costos if c["tipo"] == "variable")

        productos = conn_execute(conn, "SELECT * FROM productos").fetchall()
        valor_stock = sum(float(p["costo"]) * p["stock"] for p in productos)

        # 1) Guardar la foto completa del mes que se cierra.
        conn_execute(
            conn,
            "INSERT INTO cierres_mensuales "
            "(periodo, ingresos_totales, egresos_totales, ganancia_neta, "
            "total_activos, total_pasivos, patrimonio_neto, total_costos_fijos, total_costos_variables, "
            "valor_stock, fecha_cierre) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                periodo, ingresos, egresos, ganancia,
                total_activos, total_pasivos, patrimonio_neto,
                total_costos_fijos, total_costos_variables, valor_stock,
                ahora().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

        # 2) Reiniciar todo para arrancar el mes siguiente en cero.
        #    El stock de productos (cantidades) y los socios (CapTable) NO se tocan,
        #    pero el costo de cada producto se pone en $0 para que la valorización arranque en cero
        #    hasta que se vuelva a cargar el costo.
        conn_execute(conn, "UPDATE productos SET costo = 0")
        conn_execute(conn, "DELETE FROM venta_items")
        conn_execute(conn, "DELETE FROM ventas")
        conn_execute(conn, "DELETE FROM movimientos_caja")
        conn_execute(conn, "DELETE FROM activos")
        conn_execute(conn, "DELETE FROM pasivos")
        conn_execute(conn, "DELETE FROM costos_fijos")

        conn.commit()
        release_db(conn)
        registrar_historial(
            session.get("usuario_nombre"),
            "Cierre mensual generado (reinicio de ventas, caja, finanzas y costos)",
            periodo,
            ganancia,
        )
        flash(
            f"Cierre del período {periodo} guardado. Ventas, flujo de caja, estructura financiera y costos se reiniciaron para el nuevo mes.",
            "success",
        )
        return redirect(url_for("cierre_mensual"))

    cierres = conn_execute(conn, "SELECT * FROM cierres_mensuales ORDER BY id DESC").fetchall()
    release_db(conn)
    return render_template("cierre_mensual.html", cierres=cierres)


# Se ejecuta siempre al cargar el módulo (tanto con "python app.py" como con gunicorn),
# para asegurar que las tablas existan en la base de Neon.
init_db()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
