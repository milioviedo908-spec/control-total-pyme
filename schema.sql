-- Control Total PyME - Esquema de Base de Datos (PostgreSQL / Neon)

DROP TABLE IF EXISTS venta_items;
DROP TABLE IF EXISTS ventas;
DROP TABLE IF EXISTS movimientos_caja;
DROP TABLE IF EXISTS costos_fijos;
DROP TABLE IF EXISTS activos;
DROP TABLE IF EXISTS pasivos;
DROP TABLE IF EXISTS socios;
DROP TABLE IF EXISTS historial;
DROP TABLE IF EXISTS cierres_mensuales;
DROP TABLE IF EXISTS productos;
DROP TABLE IF EXISTS config;
DROP TABLE IF EXISTS usuarios;

CREATE TABLE usuarios (
    id SERIAL PRIMARY KEY,
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
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    precio NUMERIC(12,2) NOT NULL DEFAULT 0,
    costo NUMERIC(12,2) NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    stock_minimo INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE ventas (
    id SERIAL PRIMARY KEY,
    fecha TEXT NOT NULL,
    total NUMERIC(12,2) NOT NULL,
    usuario TEXT,
    tipo_pago TEXT DEFAULT 'Efectivo'
);

CREATE TABLE venta_items (
    id SERIAL PRIMARY KEY,
    venta_id INTEGER NOT NULL REFERENCES ventas(id),
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    producto_nombre TEXT,
    cantidad INTEGER NOT NULL,
    precio_unitario NUMERIC(12,2) NOT NULL
);

CREATE TABLE movimientos_caja (
    id SERIAL PRIMARY KEY,
    fecha TEXT NOT NULL,
    tipo TEXT NOT NULL,
    categoria TEXT,
    monto NUMERIC(12,2) NOT NULL,
    descripcion TEXT
);

CREATE TABLE costos_fijos (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    monto NUMERIC(12,2) NOT NULL,
    periodicidad TEXT DEFAULT 'Mensual',
    tipo TEXT DEFAULT 'fijo'
);

CREATE TABLE activos (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    tipo TEXT,
    monto NUMERIC(12,2) NOT NULL
);

CREATE TABLE pasivos (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    monto NUMERIC(12,2) NOT NULL
);

CREATE TABLE socios (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    porcentaje NUMERIC(5,2) NOT NULL
);

CREATE TABLE historial (
    id SERIAL PRIMARY KEY,
    fecha TEXT NOT NULL,
    usuario TEXT,
    accion TEXT NOT NULL,
    detalle TEXT,
    monto NUMERIC(12,2)
);

CREATE TABLE cierres_mensuales (
    id SERIAL PRIMARY KEY,
    periodo TEXT NOT NULL,
    ingresos_totales NUMERIC(12,2),
    egresos_totales NUMERIC(12,2),
    ganancia_neta NUMERIC(12,2),
    total_activos NUMERIC(12,2),
    total_pasivos NUMERIC(12,2),
    patrimonio_neto NUMERIC(12,2),
    total_costos_fijos NUMERIC(12,2),
    total_costos_variables NUMERIC(12,2),
    fecha_cierre TEXT
);
