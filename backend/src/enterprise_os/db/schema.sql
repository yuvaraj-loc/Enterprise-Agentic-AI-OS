PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS employees (
    employee_id INTEGER PRIMARY KEY CHECK (employee_id > 0),
    full_name TEXT NOT NULL CHECK (length(trim(full_name)) BETWEEN 1 AND 120),
    department TEXT NOT NULL CHECK (length(trim(department)) BETWEEN 1 AND 120),
    job_title TEXT NOT NULL CHECK (length(trim(job_title)) BETWEEN 1 AND 120),
    email TEXT NOT NULL COLLATE NOCASE UNIQUE
        CHECK (length(trim(email)) BETWEEN 3 AND 254 AND instr(email, '@') > 1)
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id INTEGER PRIMARY KEY CHECK (ticket_id > 0),
    assigned_employee_id INTEGER REFERENCES employees(employee_id) ON DELETE SET NULL,
    customer_id TEXT NOT NULL CHECK (length(trim(customer_id)) BETWEEN 1 AND 64),
    order_id TEXT NOT NULL CHECK (length(trim(order_id)) BETWEEN 1 AND 64),
    category TEXT NOT NULL
        CHECK (category IN ('refund_request', 'general', 'shipping')),
    status TEXT NOT NULL
        CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    delivery_date TEXT NOT NULL CHECK (date(delivery_date) IS NOT NULL),
    request_date TEXT NOT NULL
        CHECK (date(request_date) IS NOT NULL AND request_date >= delivery_date),
    item_condition TEXT NOT NULL CHECK (length(trim(item_condition)) BETWEEN 1 AND 500),
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    requested_refund_method TEXT NOT NULL
        CHECK (requested_refund_method IN ('original_payment_method', 'store_credit', 'gift_card')),
    description TEXT NOT NULL CHECK (length(trim(description)) BETWEEN 1 AND 1000)
);

CREATE INDEX IF NOT EXISTS tickets_assigned_employee_id_idx
    ON tickets(assigned_employee_id);

CREATE INDEX IF NOT EXISTS tickets_status_idx
    ON tickets(status);
