package plugins

import "net/http"

// Plugin defines the interface for daemon plugins.
// Each plugin registers its own routes on the provided mux.
type Plugin interface {
	Name() string
	RegisterRoutes(mux *http.ServeMux)
}
