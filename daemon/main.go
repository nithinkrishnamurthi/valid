package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/nithinkrishnamurthi/valid/daemon/audit"
	"github.com/nithinkrishnamurthi/valid/daemon/plugins"
	"github.com/nithinkrishnamurthi/valid/daemon/policy"
)

func main() {
	port := flag.Int("port", 9090, "port to listen on")
	mcpConfig := flag.String("mcp-config", "", "path to MCP server configuration file")
	policyFlag := flag.String("policy", "", "path to policy JSON file")
	auditFlag := flag.String("audit-log", "", "path to audit log file")
	flag.Parse()

	token := os.Getenv("DAEMON_TOKEN")
	if token == "" {
		log.Fatal("DAEMON_TOKEN environment variable is required")
	}

	// Load policy engine (nil = pass-through, no behavior change).
	var policyEngine *policy.Engine
	if *policyFlag != "" {
		var err error
		policyEngine, err = policy.Load(*policyFlag)
		if err != nil {
			log.Fatalf("Failed to load policy: %v", err)
		}
		log.Printf("Policy loaded from %s", *policyFlag)
	}

	// Create audit logger (nil = no logging).
	var auditLogger *audit.Logger
	if *auditFlag != "" {
		var err error
		auditLogger, err = audit.New(*auditFlag)
		if err != nil {
			log.Fatalf("Failed to create audit logger: %v", err)
		}
		defer auditLogger.Close()
		log.Printf("Audit log: %s", *auditFlag)
	}

	mux := http.NewServeMux()

	// Health endpoint (no auth required)
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})

	// Register plugins on an auth-protected mux
	authedMux := http.NewServeMux()
	allPlugins := []plugins.Plugin{
		&plugins.ExecPlugin{Policy: policyEngine, Audit: auditLogger},
	}

	if *mcpConfig != "" {
		mcpPlugin, err := plugins.NewMCPPlugin(*mcpConfig, policyEngine, auditLogger)
		if err != nil {
			log.Fatalf("Failed to initialize MCP plugin: %v", err)
		}
		defer mcpPlugin.Shutdown()
		allPlugins = append(allPlugins, mcpPlugin)
	}

	for _, p := range allPlugins {
		p.RegisterRoutes(authedMux)
		log.Printf("Registered plugin: %s", p.Name())
	}

	// Mount authed routes through auth middleware
	mux.Handle("/", authMiddleware(token, authedMux))

	addr := fmt.Sprintf(":%d", *port)
	log.Printf("Daemon listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func authMiddleware(token string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header := r.Header.Get("Authorization")
		if header == "" || header != "Bearer "+token {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(w, r)
	})
}
