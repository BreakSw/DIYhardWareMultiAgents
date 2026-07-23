CREATE DATABASE IF NOT EXISTS diy_agents CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE diy_agents;

CREATE TABLE IF NOT EXISTS hardware_parts (
  id INT PRIMARY KEY AUTO_INCREMENT,
  category VARCHAR(32) NOT NULL,
  name VARCHAR(160) NOT NULL,
  brand VARCHAR(64) NOT NULL,
  specs JSON NOT NULL,
  price INT NOT NULL,
  stock_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
  source_url VARCHAR(500) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_hardware_category (category)
);

CREATE TABLE IF NOT EXISTS compatibility_rules (
  id INT PRIMARY KEY AUTO_INCREMENT,
  rule_type VARCHAR(64) NOT NULL,
  rule_expression TEXT NOT NULL,
  severity VARCHAR(16) NOT NULL DEFAULT 'error',
  message_template VARCHAR(500) NOT NULL,
  INDEX idx_rule_type (rule_type)
);

CREATE TABLE IF NOT EXISTS recommendation_tasks (
  id VARCHAR(64) PRIMARY KEY,
  raw_requirement TEXT NOT NULL,
  parsed_profile JSON NOT NULL,
  status VARCHAR(32) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_task_status (status)
);

CREATE TABLE IF NOT EXISTS recommendation_results (
  id INT PRIMARY KEY AUTO_INCREMENT,
  task_id VARCHAR(64) NOT NULL,
  result_payload JSON NOT NULL,
  score INT NOT NULL,
  total_price INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_result_task (task_id)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
  id INT PRIMARY KEY AUTO_INCREMENT,
  hardware_part_id INT NOT NULL,
  price INT NOT NULL,
  source VARCHAR(64) NOT NULL,
  captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_price_part_time (hardware_part_id, captured_at)
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  task_id VARCHAR(64) NOT NULL,
  agent_name VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  input_payload JSON NULL,
  output_payload JSON NULL,
  duration_ms INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_agent_task (task_id)
);

CREATE TABLE IF NOT EXISTS tool_call_logs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  task_id VARCHAR(64) NOT NULL,
  tool_name VARCHAR(64) NOT NULL,
  input_payload JSON NULL,
  output_payload JSON NULL,
  status VARCHAR(32) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_tool_task (task_id)
);

INSERT INTO compatibility_rules (rule_type, rule_expression, severity, message_template)
SELECT 'cpu_socket', 'cpu.socket = motherboard.socket', 'error', 'CPU 与主板插槽不兼容'
WHERE NOT EXISTS (SELECT 1 FROM compatibility_rules WHERE rule_type = 'cpu_socket');

INSERT INTO compatibility_rules (rule_type, rule_expression, severity, message_template)
SELECT 'memory_type', 'memory.memory_type = motherboard.memory_type', 'error', '内存类型与主板不匹配'
WHERE NOT EXISTS (SELECT 1 FROM compatibility_rules WHERE rule_type = 'memory_type');
