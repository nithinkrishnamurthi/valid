package policy

import (
	"os"
	"path/filepath"
	"testing"
)

func TestEvaluate(t *testing.T) {
	tests := []struct {
		name    string
		policy  Policy
		tool    string
		args    map[string]interface{}
		allowed bool
		ruleID  string
	}{
		{
			name:    "default deny, no rules",
			policy:  Policy{Default: "deny"},
			tool:    "exec",
			args:    map[string]interface{}{"command": "ls"},
			allowed: false,
			ruleID:  "default",
		},
		{
			name:    "default allow, no rules",
			policy:  Policy{Default: "allow"},
			tool:    "exec",
			args:    map[string]interface{}{"command": "rm -rf /"},
			allowed: true,
			ruleID:  "default",
		},
		{
			name: "exec allowed by prefix match",
			policy: Policy{
				Default: "deny",
				Rules: []Rule{{
					ID:      "allow-tests",
					Tool:    "exec",
					AllowIf: &Condition{CommandPrefix: []string{"npm test", "npm run lint"}},
				}},
			},
			tool:    "exec",
			args:    map[string]interface{}{"command": "npm test --coverage"},
			allowed: true,
			ruleID:  "allow-tests",
		},
		{
			name: "exec denied, no prefix match",
			policy: Policy{
				Default: "deny",
				Rules: []Rule{{
					ID:      "allow-tests",
					Tool:    "exec",
					AllowIf: &Condition{CommandPrefix: []string{"npm test"}},
				}},
			},
			tool:    "exec",
			args:    map[string]interface{}{"command": "rm -rf /"},
			allowed: false,
			ruleID:  "default",
		},
		{
			name: "word boundary: npm test does not match npm testMalicious",
			policy: Policy{
				Default: "deny",
				Rules: []Rule{{
					ID:      "allow-tests",
					Tool:    "exec",
					AllowIf: &Condition{CommandPrefix: []string{"npm test"}},
				}},
			},
			tool:    "exec",
			args:    map[string]interface{}{"command": "npm testMalicious"},
			allowed: false,
			ruleID:  "default",
		},
		{
			name: "exact prefix match (no trailing chars)",
			policy: Policy{
				Default: "deny",
				Rules: []Rule{{
					ID:      "allow-tests",
					Tool:    "exec",
					AllowIf: &Condition{CommandPrefix: []string{"npm test"}},
				}},
			},
			tool:    "exec",
			args:    map[string]interface{}{"command": "npm test"},
			allowed: true,
			ruleID:  "allow-tests",
		},
		{
			name: "glob tool match: browser_*",
			policy: Policy{
				Default: "deny",
				Rules: []Rule{{
					ID:      "allow-browse",
					Tool:    "browser_*",
					AllowIf: &Condition{ArgsURL: "http://localhost:3000/**"},
				}},
			},
			tool:    "browser_navigate",
			args:    map[string]interface{}{"url": "http://localhost:3000/dashboard"},
			allowed: true,
			ruleID:  "allow-browse",
		},
		{
			name: "glob tool match: browser_* does not match exec",
			policy: Policy{
				Default: "deny",
				Rules: []Rule{{
					ID:      "allow-browse",
					Tool:    "browser_*",
					AllowIf: &Condition{ArgsURL: "http://localhost:3000/**"},
				}},
			},
			tool:    "exec",
			args:    map[string]interface{}{"command": "ls"},
			allowed: false,
			ruleID:  "default",
		},
		{
			name: "deny_if takes priority over allow_if",
			policy: Policy{
				Default: "deny",
				Rules: []Rule{{
					ID:      "browse-no-admin",
					Tool:    "browser_*",
					AllowIf: &Condition{ArgsURL: "http://localhost:3000/**"},
					DenyIf:  &Condition{ArgsURL: "http://localhost:3000/admin/**"},
				}},
			},
			tool:    "browser_navigate",
			args:    map[string]interface{}{"url": "http://localhost:3000/admin/users"},
			allowed: false,
			ruleID:  "browse-no-admin",
		},
		{
			name: "URL allowed when not matching deny pattern",
			policy: Policy{
				Default: "deny",
				Rules: []Rule{{
					ID:      "browse-no-admin",
					Tool:    "browser_*",
					AllowIf: &Condition{ArgsURL: "http://localhost:3000/**"},
					DenyIf:  &Condition{ArgsURL: "http://localhost:3000/admin/**"},
				}},
			},
			tool:    "browser_navigate",
			args:    map[string]interface{}{"url": "http://localhost:3000/products"},
			allowed: true,
			ruleID:  "browse-no-admin",
		},
		{
			name: "fall-through to second rule when first condition doesn't fire",
			policy: Policy{
				Default: "deny",
				Rules: []Rule{
					{
						ID:      "allow-tests",
						Tool:    "exec",
						AllowIf: &Condition{CommandPrefix: []string{"npm test"}},
					},
					{
						ID:      "allow-git",
						Tool:    "exec",
						AllowIf: &Condition{CommandPrefix: []string{"git log"}},
					},
				},
			},
			tool:    "exec",
			args:    map[string]interface{}{"command": "git log --oneline"},
			allowed: true,
			ruleID:  "allow-git",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			e := &Engine{policy: tt.policy}
			d := e.Evaluate(tt.tool, tt.args)
			if d.Allowed != tt.allowed {
				t.Errorf("Allowed = %v, want %v", d.Allowed, tt.allowed)
			}
			if d.RuleID != tt.ruleID {
				t.Errorf("RuleID = %q, want %q", d.RuleID, tt.ruleID)
			}
		})
	}
}

func TestMatchToolName(t *testing.T) {
	tests := []struct {
		pattern string
		name    string
		want    bool
	}{
		{"exec", "exec", true},
		{"exec", "mcp", false},
		{"browser_*", "browser_navigate", true},
		{"browser_*", "browser_click", true},
		{"browser_*", "exec", false},
		{"*", "anything", true},
	}
	for _, tt := range tests {
		t.Run(tt.pattern+"_"+tt.name, func(t *testing.T) {
			if got := matchToolName(tt.pattern, tt.name); got != tt.want {
				t.Errorf("matchToolName(%q, %q) = %v, want %v", tt.pattern, tt.name, got, tt.want)
			}
		})
	}
}

func TestGlobMatch(t *testing.T) {
	tests := []struct {
		pattern string
		value   string
		want    bool
	}{
		{"/foo/**", "/foo/bar", true},
		{"/foo/**", "/foo/bar/baz", true},
		{"/foo/**", "/foo", true},
		{"/foo/**", "/bar", false},
		{"/foo/bar", "/foo/bar", true},
		{"/foo/bar", "/foo/baz", false},
	}
	for _, tt := range tests {
		t.Run(tt.pattern+"_"+tt.value, func(t *testing.T) {
			if got := globMatch(tt.pattern, tt.value); got != tt.want {
				t.Errorf("globMatch(%q, %q) = %v, want %v", tt.pattern, tt.value, got, tt.want)
			}
		})
	}
}

func TestMatchCommandPrefix(t *testing.T) {
	tests := []struct {
		command  string
		prefixes []string
		want     bool
	}{
		{"npm test --coverage", []string{"npm test"}, true},
		{"npm test", []string{"npm test"}, true},
		{"npm testMalicious", []string{"npm test"}, false},
		{"npm run lint", []string{"npm test", "npm run lint"}, true},
		{"rm -rf /", []string{"npm test"}, false},
		{"", []string{"npm test"}, false},
	}
	for _, tt := range tests {
		t.Run(tt.command, func(t *testing.T) {
			got, _ := matchCommandPrefix(tt.command, tt.prefixes)
			if got != tt.want {
				t.Errorf("matchCommandPrefix(%q, %v) = %v, want %v", tt.command, tt.prefixes, got, tt.want)
			}
		})
	}
}

func TestLoad(t *testing.T) {
	t.Run("invalid default", func(t *testing.T) {
		dir := t.TempDir()
		f := filepath.Join(dir, "policy.json")
		os.WriteFile(f, []byte(`{"default":"maybe","rules":[]}`), 0644)
		_, err := Load(f)
		if err == nil {
			t.Fatal("expected error for invalid default")
		}
	})

	t.Run("missing rule id", func(t *testing.T) {
		dir := t.TempDir()
		f := filepath.Join(dir, "policy.json")
		os.WriteFile(f, []byte(`{"default":"deny","rules":[{"tool":"exec"}]}`), 0644)
		_, err := Load(f)
		if err == nil {
			t.Fatal("expected error for missing rule id")
		}
	})

	t.Run("valid policy", func(t *testing.T) {
		dir := t.TempDir()
		f := filepath.Join(dir, "policy.json")
		os.WriteFile(f, []byte(`{"default":"deny","rules":[{"id":"r1","tool":"exec"}]}`), 0644)
		e, err := Load(f)
		if err != nil {
			t.Fatal(err)
		}
		if e.policy.Default != "deny" {
			t.Errorf("Default = %q, want deny", e.policy.Default)
		}
	})
}
