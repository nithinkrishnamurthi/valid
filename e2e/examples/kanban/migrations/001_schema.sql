CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    assignee VARCHAR(100),
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',
    status VARCHAR(20) NOT NULL DEFAULT 'backlog',
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO tasks (title, assignee, priority, status) VALUES
    ('Design login page',       'Alice', 'high',   'done'),
    ('Fix payment bug',         'Bob',   'high',   'in_progress'),
    ('Update API docs',         'Carol', 'low',    'backlog'),
    ('Add dark mode',           'Alice', 'medium', 'in_progress'),
    ('Optimize images',         'Dave',  'medium', 'backlog'),
    ('Write unit tests',        'Bob',   'high',   'backlog'),
    ('Deploy to staging',       'Carol', 'medium', 'done'),
    ('Review PR #142',          'Dave',  'low',    'in_progress'),
    ('Set up CI pipeline',      'Alice', 'high',   'backlog'),
    ('Migrate to TypeScript',   'Bob',   'low',    'done');
