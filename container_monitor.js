const http = require('http');
const { exec } = require('child_process');
const os = require('os');

// Create a simple health check server
const server = http.createServer((req, res) => {
  res.writeHead(200);
  res.end('OK');
});

// Start server on port 8080
server.listen(8080);

// Function to simulate CPU load
function simulateCPULoad() {
  const start = Date.now();
  while (Date.now() - start < 100) {
    // Intensive calculation
    Math.random() * Math.random();
  }
}

// Function to check system metrics
function checkSystem() {
  const cpuUsage = os.loadavg()[0];
  const totalMem = os.totalmem();
  const freeMem = os.freemem();
  const memUsage = ((totalMem - freeMem) / totalMem) * 100;
  
  console.log(`CPU Load: ${cpuUsage.toFixed(2)}, Memory Usage: ${memUsage.toFixed(2)}%`);
  
  // If system is too idle, generate some load
  if (cpuUsage < 0.1) {
    simulateCPULoad();
  }
}

// Periodic system check
setInterval(checkSystem, 30000);

// Periodic file touch to show activity
setInterval(() => {
  exec('touch /tmp/activity_marker');
}, 60000);

process.on('SIGTERM', () => {
  server.close(() => {
    process.exit(0);
  });
});