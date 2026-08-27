module.exports = {
  apps: [
    {
      name: 'order-book-api',
      script: '.venv/bin/uvicorn',
      args: 'app.main:app --host 0.0.0.0 --port 8000',
      cwd: '/home/user/order-book',
      interpreter: 'none',
      watch: false,
      instances: 1,
      exec_mode: 'fork',
    },
  ],
};
