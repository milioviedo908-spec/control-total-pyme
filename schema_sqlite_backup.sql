-- Control Total PyME - Esquema de Base de Datos

DROP TABLE IF EXISTS usuarios;
DROP TABLE IF EXISTS config;
DROP TABLE IF EXISTS productos;
DROP TABLE IF EXISTS ventas;
DROP TABLE IF EXISTS venta_items;
DROP TABLE IF EXISTS movimientos_caja;
DROP TABLE IF EXISTS costos_fijos;
DROP TABLE IF EXISTS activos;
DROP TABLE IF EXISTS pasivos;
DROP TABLE IF EXISTS socios;
DROP TABLE IF EXISTS historial;
DROP TABLE IF EXISTS cierres_mensuales;

CREATE TABLE usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'admin'
);

CREATE TABLE config (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    precio REAL NOT NULL DEFAULT 0,
    costo REAL NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    stock_minimo INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    total REAL NOT NULL,
    usuario TEXT,
    tipo_pago TEXT DEFAULT 'Efectivo'
);

CREATE TABLE venta_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    producto_nombre TEXT,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    FOREIGN KEY (venta_id) REFERENCES ventas(id),
    FOREIGN KEY (producto_id) REFERENCES productos(id)
);

CREATE TABLE movimientos_caja (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    tipo TEXT NOT NULL, -- 'ingreso' o 'egreso'
    categoria TEXT,
    monto REAL NOT NULL,
    descripcion TEXT
);

CREATE TABLE costos_fijos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    monto REAL NOT NULL,
    periodicidad TEXT DEFAULT 'Mensual',
    tipo TEXT DEFAULT 'fijo' -- 'fijo' o 'variable'
);

CREATE TABLE activos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    tipo TEXT,
    monto REAL NOT NULL
);

CREATE TABLE pasivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    monto REAL NOT NULL
);

CREATE TABLE socios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    porcentaje REAL NOT NULL
);

CREATE TABLE historial (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    usuario TEXT,
    accion TEXT NOT NULL,
    detalle TEXT,
    monto REAL
);

CREATE TABLE cierres_mensuales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo TEXT NOT NULL,
    ingresos_totales REAL,
    egresos_totales REAL,
    ganancia_neta REAL,
    fecha_cierre TEXT
);
