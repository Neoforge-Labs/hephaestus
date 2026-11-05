// Package ingot loads and validates an ingot's heph.toml. Maturity: experimental.
package ingot

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/BurntSushi/toml"
)

// FileName is the ingot manifest, looked up in the ingot's root directory.
const FileName = "heph.toml"

// Config is the parsed heph.toml.
type Config struct {
	Ingot Ingot `toml:"ingot"`
	Dev   Dev   `toml:"dev"`
}

// Ingot identifies the project; Name doubles as the Compose project name.
type Ingot struct {
	Name string `toml:"name"`
}

// Dev selects the local-stack fragments (see compose/).
type Dev struct {
	Fragments []string `toml:"fragments"`
}

// Compose project names must be lowercase alphanumerics, dashes or underscores.
var namePattern = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]*$`)

// Load reads and validates <dir>/heph.toml. Every error names the file.
func Load(dir string) (Config, error) {
	path := filepath.Join(dir, FileName)
	raw, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return Config{}, fmt.Errorf("no %s in %s: run heph from an ingot's root directory", FileName, dir)
		}
		return Config{}, fmt.Errorf("reading %s: %w", path, err)
	}
	var cfg Config
	md, err := toml.Decode(string(raw), &cfg)
	if err != nil {
		return Config{}, fmt.Errorf("%s is not valid TOML: %w", path, err)
	}
	if un := md.Undecoded(); len(un) > 0 {
		keys := make([]string, len(un))
		for i, k := range un {
			keys[i] = k.String()
		}
		return Config{}, fmt.Errorf("%s has unknown keys: %s", path, strings.Join(keys, ", "))
	}
	if !namePattern.MatchString(cfg.Ingot.Name) {
		return Config{}, fmt.Errorf("%s: ingot.name %q must match %s", path, cfg.Ingot.Name, namePattern)
	}
	if len(cfg.Dev.Fragments) == 0 {
		return Config{}, fmt.Errorf("%s: dev.fragments is empty; list at least one fragment, e.g. [\"telemetry\"]", path)
	}
	seen := map[string]bool{}
	for _, f := range cfg.Dev.Fragments {
		if seen[f] {
			return Config{}, fmt.Errorf("%s: duplicate fragment %q in dev.fragments", path, f)
		}
		seen[f] = true
	}
	return cfg, nil
}
