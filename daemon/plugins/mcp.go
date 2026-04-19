package plugins

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"sync"
	"sync/atomic"

	"github.com/nithinkrishnamurthi/valid/daemon/audit"
	"github.com/nithinkrishnamurthi/valid/daemon/policy"
)

// ---------- config ----------

type MCPConfig struct {
	MCPServers map[string]MCPServerConfig `json:"mcpServers"`
}

type MCPServerConfig struct {
	Command string            `json:"command"`
	Args    []string          `json:"args"`
	Env     map[string]string `json:"env,omitempty"`
}

// ---------- JSON-RPC ----------

type jsonrpcRequest struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      int64       `json:"id,omitempty"`
	Method  string      `json:"method"`
	Params  interface{} `json:"params,omitempty"`
}

type jsonrpcResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      *int64          `json:"id,omitempty"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *jsonrpcError   `json:"error,omitempty"`
}

type jsonrpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// ---------- MCP tool schema ----------

type MCPTool struct {
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	InputSchema json.RawMessage `json:"inputSchema,omitempty"`
}

type toolsListResult struct {
	Tools []MCPTool `json:"tools"`
}

// ---------- child process ----------

type mcpChild struct {
	name    string
	cmd     *exec.Cmd
	stdin   io.WriteCloser
	scanner *bufio.Scanner
	mu      sync.Mutex
	nextID  atomic.Int64
	tools   []MCPTool
}

// send issues a JSON-RPC request and blocks until the matching response
// arrives, skipping any interleaved notifications.
func (c *mcpChild) send(method string, params interface{}) (*jsonrpcResponse, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	id := c.nextID.Add(1)
	req := jsonrpcRequest{
		JSONRPC: "2.0",
		ID:      id,
		Method:  method,
		Params:  params,
	}

	data, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}
	if _, err := c.stdin.Write(append(data, '\n')); err != nil {
		return nil, fmt.Errorf("write stdin: %w", err)
	}

	for c.scanner.Scan() {
		line := c.scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		var resp jsonrpcResponse
		if err := json.Unmarshal(line, &resp); err != nil {
			continue
		}
		if resp.ID == nil {
			continue // notification, skip
		}
		if *resp.ID == id {
			return &resp, nil
		}
	}
	if err := c.scanner.Err(); err != nil {
		return nil, fmt.Errorf("read stdout: %w", err)
	}
	return nil, fmt.Errorf("child %q closed stdout", c.name)
}

// notify sends a JSON-RPC notification (no id, no response expected).
func (c *mcpChild) notify(method string, params interface{}) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	req := jsonrpcRequest{JSONRPC: "2.0", Method: method, Params: params}
	data, err := json.Marshal(req)
	if err != nil {
		return err
	}
	_, err = c.stdin.Write(append(data, '\n'))
	return err
}

// ---------- MCPPlugin ----------

type MCPPlugin struct {
	children map[string]*mcpChild
	toolMap  map[string]*mcpChild // tool name → owning child
	allTools []MCPTool
	policy   *policy.Engine
	audit    *audit.Logger
}

func NewMCPPlugin(configPath string, pol *policy.Engine, aud *audit.Logger) (*MCPPlugin, error) {
	f, err := os.Open(configPath)
	if err != nil {
		return nil, fmt.Errorf("open config: %w", err)
	}
	defer f.Close()

	var cfg MCPConfig
	if err := json.NewDecoder(f).Decode(&cfg); err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}

	p := &MCPPlugin{
		children: make(map[string]*mcpChild),
		toolMap:  make(map[string]*mcpChild),
		policy:   pol,
		audit:    aud,
	}

	for name, sc := range cfg.MCPServers {
		child, err := p.spawnChild(name, sc)
		if err != nil {
			p.Shutdown()
			return nil, fmt.Errorf("start MCP server %q: %w", name, err)
		}
		p.children[name] = child

		for _, t := range child.tools {
			if _, dup := p.toolMap[t.Name]; dup {
				log.Printf("[mcp] warning: duplicate tool %q, last writer wins (server %q)", t.Name, name)
			}
			p.toolMap[t.Name] = child
			p.allTools = append(p.allTools, t)
		}
		log.Printf("[mcp] server %q: %d tools", name, len(child.tools))
	}
	return p, nil
}

func (p *MCPPlugin) spawnChild(name string, sc MCPServerConfig) (*mcpChild, error) {
	cmd := exec.Command(sc.Command, sc.Args...)
	cmd.Env = os.Environ()
	for k, v := range sc.Env {
		cmd.Env = append(cmd.Env, k+"="+v)
	}
	cmd.Stderr = os.Stderr

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}

	child := &mcpChild{
		name:    name,
		cmd:     cmd,
		stdin:   stdin,
		scanner: bufio.NewScanner(stdout),
	}
	// MCP messages can be large (base64 images).
	child.scanner.Buffer(make([]byte, 0, 64*1024), 10*1024*1024)

	// --- MCP handshake ---
	initResp, err := child.send("initialize", map[string]interface{}{
		"protocolVersion": "2024-11-05",
		"capabilities":    map[string]interface{}{},
		"clientInfo":      map[string]string{"name": "valid-daemon", "version": "0.1.0"},
	})
	if err != nil {
		cmd.Process.Kill()
		return nil, fmt.Errorf("initialize: %w", err)
	}
	if initResp.Error != nil {
		cmd.Process.Kill()
		return nil, fmt.Errorf("initialize: %s", initResp.Error.Message)
	}

	if err := child.notify("notifications/initialized", nil); err != nil {
		cmd.Process.Kill()
		return nil, fmt.Errorf("initialized notify: %w", err)
	}

	// --- discover tools ---
	tlResp, err := child.send("tools/list", map[string]interface{}{})
	if err != nil {
		cmd.Process.Kill()
		return nil, fmt.Errorf("tools/list: %w", err)
	}
	if tlResp.Error != nil {
		cmd.Process.Kill()
		return nil, fmt.Errorf("tools/list: %s", tlResp.Error.Message)
	}
	var tlResult toolsListResult
	if err := json.Unmarshal(tlResp.Result, &tlResult); err != nil {
		cmd.Process.Kill()
		return nil, fmt.Errorf("parse tools: %w", err)
	}
	child.tools = tlResult.Tools
	return child, nil
}

func (p *MCPPlugin) Shutdown() {
	for name, c := range p.children {
		c.stdin.Close()
		c.cmd.Process.Kill()
		c.cmd.Wait()
		log.Printf("[mcp] server %q stopped", name)
	}
}

func (p *MCPPlugin) Name() string { return "mcp" }

func (p *MCPPlugin) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /tools", p.handleListTools)
	mux.HandleFunc("POST /tools/call", p.handleCallTool)
}

// ---------- HTTP handlers ----------

type callToolRequest struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments"`
}

func (p *MCPPlugin) handleListTools(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{"tools": p.allTools})
}

func (p *MCPPlugin) handleCallTool(w http.ResponseWriter, r *http.Request) {
	var req callToolRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}

	child, ok := p.toolMap[req.Name]
	if !ok {
		http.Error(w, fmt.Sprintf(`{"error":"unknown tool: %s"}`, req.Name), http.StatusNotFound)
		return
	}

	// Policy check.
	if p.policy != nil {
		decision := p.policy.Evaluate(req.Name, req.Arguments)
		decisionStr := "allow"
		if !decision.Allowed {
			decisionStr = "deny"
		}
		if p.audit != nil {
			p.audit.Log(req.Name, req.Arguments, decisionStr, decision.RuleID)
		}
		if !decision.Allowed {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(map[string]string{
				"error":   "policy_denied",
				"rule_id": decision.RuleID,
				"hint":    decision.Hint,
			})
			return
		}
	}

	resp, err := child.send("tools/call", map[string]interface{}{
		"name":      req.Name,
		"arguments": req.Arguments,
	})
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error":"%s"}`, err.Error()), http.StatusInternalServerError)
		return
	}
	if resp.Error != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]interface{}{"error": resp.Error.Message})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write(resp.Result)
}
