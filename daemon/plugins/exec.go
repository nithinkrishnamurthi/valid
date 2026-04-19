package plugins

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"os/exec"
	"time"
)

type ExecPlugin struct{}

func (p *ExecPlugin) Name() string { return "exec" }

func (p *ExecPlugin) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /exec", p.handleExec)
}

type execRequest struct {
	Command string `json:"command"`
}

type execResponse struct {
	Stdout   string `json:"stdout"`
	Stderr   string `json:"stderr"`
	ExitCode int    `json:"exit_code"`
}

func (p *ExecPlugin) handleExec(w http.ResponseWriter, r *http.Request) {
	var req execRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}

	if req.Command == "" {
		http.Error(w, `{"error":"command is required"}`, http.StatusBadRequest)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "bash", "-c", req.Command)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()

	resp := execResponse{
		Stdout: stdout.String(),
		Stderr: stderr.String(),
	}

	if ctx.Err() == context.DeadlineExceeded {
		resp.ExitCode = -1
		resp.Stderr = resp.Stderr + "\n[daemon] command timed out after 30s"
	} else if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			resp.ExitCode = exitErr.ExitCode()
		} else {
			resp.ExitCode = -1
			resp.Stderr = resp.Stderr + "\n[daemon] " + err.Error()
		}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}
