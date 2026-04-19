package policy

import (
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"strings"
)

// Policy defines the access control rules loaded from a JSON file.
type Policy struct {
	Default string `json:"default"` // "allow" or "deny"
	Rules   []Rule `json:"rules"`
}

// Rule is a single policy rule that matches on tool name and evaluates conditions.
type Rule struct {
	ID      string     `json:"id"`
	Tool    string     `json:"tool"` // glob pattern
	AllowIf *Condition `json:"allow_if,omitempty"`
	DenyIf  *Condition `json:"deny_if,omitempty"`
}

// Condition specifies matching criteria within a rule.
type Condition struct {
	CommandPrefix []string `json:"command_prefix,omitempty"`
	ArgsURL       string   `json:"args.url,omitempty"`
}

// Decision is the result of policy evaluation.
type Decision struct {
	Allowed bool
	RuleID  string
	Hint    string
}

// Engine holds a loaded policy and evaluates requests against it.
type Engine struct {
	policy Policy
}

// Load reads a policy JSON file and returns an Engine.
func Load(path string) (*Engine, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read policy file: %w", err)
	}
	var p Policy
	if err := json.Unmarshal(data, &p); err != nil {
		return nil, fmt.Errorf("parse policy file: %w", err)
	}
	if p.Default != "allow" && p.Default != "deny" {
		return nil, fmt.Errorf("policy default must be \"allow\" or \"deny\", got %q", p.Default)
	}
	for i, r := range p.Rules {
		if r.ID == "" {
			return nil, fmt.Errorf("rule %d: id is required", i)
		}
		if r.Tool == "" {
			return nil, fmt.Errorf("rule %d (%s): tool is required", i, r.ID)
		}
	}
	return &Engine{policy: p}, nil
}

// Evaluate checks a tool invocation against the policy.
// Returns a Decision indicating whether the call is allowed.
//
// Algorithm: rules are evaluated in order. The first rule whose tool glob
// matches is the candidate. Within that rule, deny_if is checked first
// (wins if matched), then allow_if. If neither condition fires, evaluation
// falls through to the next rule. If no rule matches, the default applies.
func (e *Engine) Evaluate(tool string, args map[string]interface{}) Decision {
	for _, rule := range e.policy.Rules {
		if !matchToolName(rule.Tool, tool) {
			continue
		}

		// deny_if takes priority within a matched rule.
		if rule.DenyIf != nil && matchCondition(rule.DenyIf, tool, args) {
			return Decision{
				Allowed: false,
				RuleID:  rule.ID,
				Hint:    buildHint(rule, false),
			}
		}

		if rule.AllowIf != nil && matchCondition(rule.AllowIf, tool, args) {
			return Decision{
				Allowed: true,
				RuleID:  rule.ID,
			}
		}

		// Tool matched but neither condition fired — fall through.
	}

	// No rule matched; apply default.
	allowed := e.policy.Default == "allow"
	return Decision{
		Allowed: allowed,
		RuleID:  "default",
		Hint:    hintForDefault(allowed),
	}
}

// matchCondition checks if a condition matches the given tool call.
func matchCondition(c *Condition, tool string, args map[string]interface{}) bool {
	if len(c.CommandPrefix) > 0 {
		cmd, _ := args["command"].(string)
		matched, _ := matchCommandPrefix(cmd, c.CommandPrefix)
		return matched
	}
	if c.ArgsURL != "" {
		argURL, _ := args["url"].(string)
		if argURL == "" {
			return false
		}
		return matchURLPattern(c.ArgsURL, argURL)
	}
	return false
}

// matchURLPattern matches a URL value against a glob pattern.
// The pattern is applied to the path component of the URL, while scheme+host
// use glob matching on the combined scheme://host:port portion.
func matchURLPattern(pattern, value string) bool {
	pu, err := url.Parse(pattern)
	if err != nil {
		return globMatch(pattern, value)
	}
	vu, err := url.Parse(value)
	if err != nil {
		return false
	}

	// Match scheme://host (with port if present) using glob.
	patternBase := pu.Scheme + "://" + pu.Host
	valueBase := vu.Scheme + "://" + vu.Host
	if !globMatch(patternBase, valueBase) {
		return false
	}

	// Match path using glob.
	return globMatch(pu.Path, vu.Path)
}

func buildHint(rule Rule, allowed bool) string {
	if allowed {
		return ""
	}
	var parts []string
	if rule.AllowIf != nil && len(rule.AllowIf.CommandPrefix) > 0 {
		parts = append(parts, "command must start with one of: "+strings.Join(rule.AllowIf.CommandPrefix, ", "))
	}
	if rule.DenyIf != nil && rule.DenyIf.ArgsURL != "" {
		parts = append(parts, "URL matched deny pattern: "+rule.DenyIf.ArgsURL)
	}
	if len(parts) == 0 {
		return "request denied by rule " + rule.ID
	}
	return strings.Join(parts, "; ")
}

func hintForDefault(allowed bool) string {
	if allowed {
		return ""
	}
	return "no matching policy rule; default is deny"
}
