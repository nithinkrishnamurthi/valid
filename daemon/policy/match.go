package policy

import (
	"path"
	"strings"
)

// matchToolName checks if a tool name matches a glob pattern.
// Uses path.Match semantics: * matches any sequence of non-separator characters.
func matchToolName(pattern, name string) bool {
	matched, err := path.Match(pattern, name)
	if err != nil {
		return false
	}
	return matched
}

// globMatch matches a value against a glob pattern with support for /**
// (match any path suffix). For patterns ending in /**, the value must start
// with the prefix before /**. Otherwise falls back to path.Match.
func globMatch(pattern, value string) bool {
	if strings.HasSuffix(pattern, "/**") {
		prefix := strings.TrimSuffix(pattern, "/**")
		// Match the prefix itself or anything under it.
		if value == prefix {
			return true
		}
		return strings.HasPrefix(value, prefix+"/")
	}
	matched, err := path.Match(pattern, value)
	if err != nil {
		return false
	}
	return matched
}

// matchCommandPrefix checks if a command starts with any of the given prefixes,
// enforcing a word boundary: the character after the prefix must be a space,
// tab, or end-of-string. Returns whether it matched and which prefix matched.
func matchCommandPrefix(command string, prefixes []string) (bool, string) {
	for _, p := range prefixes {
		if !strings.HasPrefix(command, p) {
			continue
		}
		// Word boundary: next char must be space, tab, or end of string.
		if len(command) == len(p) {
			return true, p
		}
		next := command[len(p)]
		if next == ' ' || next == '\t' {
			return true, p
		}
	}
	return false, ""
}
