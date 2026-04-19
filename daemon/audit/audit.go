package audit

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"log"
	"os"
	"sync"
	"time"
)

// Entry is a single audit log record.
type Entry struct {
	TS       string `json:"ts"`
	Tool     string `json:"tool"`
	ArgsHash string `json:"args_hash"`
	Decision string `json:"decision"` // "allow" or "deny"
	RuleID   string `json:"rule_id"`
}

// Logger writes structured JSON audit log lines to a file and stderr.
type Logger struct {
	mu   sync.Mutex
	file *os.File
}

// New creates a Logger that appends to the given file path.
func New(path string) (*Logger, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return nil, err
	}
	return &Logger{file: f}, nil
}

// Log writes an audit entry as a JSON line to the file and stderr.
func (l *Logger) Log(tool string, args map[string]interface{}, decision, ruleID string) {
	entry := Entry{
		TS:       time.Now().UTC().Format(time.RFC3339),
		Tool:     tool,
		ArgsHash: hashArgs(args),
		Decision: decision,
		RuleID:   ruleID,
	}

	data, err := json.Marshal(entry)
	if err != nil {
		log.Printf("[audit] marshal error: %v", err)
		return
	}
	line := append(data, '\n')

	l.mu.Lock()
	defer l.mu.Unlock()

	l.file.Write(line)
	os.Stderr.Write(line)
}

// Close closes the underlying file.
func (l *Logger) Close() {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.file.Close()
}

func hashArgs(args map[string]interface{}) string {
	data, err := json.Marshal(args)
	if err != nil {
		return "error"
	}
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:8]) // 16 hex chars
}
