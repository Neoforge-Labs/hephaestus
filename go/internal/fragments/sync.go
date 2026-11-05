package fragments

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// syncable reports whether a file in compose/ belongs in the embedded copy:
// the fragments and the JSON support files they mount. moon.yml and test/ stay.
func syncable(name string) bool {
	ext := filepath.Ext(name)
	return ext == ".yaml" || ext == ".json"
}

func listSyncable(dir string) (map[string][]byte, error) {
	ents, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	out := map[string][]byte{}
	for _, e := range ents {
		if e.IsDir() || !syncable(e.Name()) {
			continue
		}
		b, err := os.ReadFile(filepath.Join(dir, e.Name()))
		if err != nil {
			return nil, err
		}
		out[e.Name()] = b
	}
	return out, nil
}

// Sync makes dst an exact copy of src's fragment files, removing stale ones
// (but keeping .gitkeep).
func Sync(src, dst string) error {
	want, err := listSyncable(src)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dst, 0o755); err != nil {
		return err
	}
	have, err := listSyncable(dst)
	if err != nil {
		return err
	}
	for name := range have {
		if _, ok := want[name]; !ok {
			if err := os.Remove(filepath.Join(dst, name)); err != nil {
				return err
			}
		}
	}
	for name, b := range want {
		if err := os.WriteFile(filepath.Join(dst, name), b, 0o644); err != nil {
			return err
		}
	}
	return nil
}

// Check returns an error listing every file where dst differs from src
// (modified, missing or extra). CI uses it to stop the embedded copy drifting.
func Check(src, dst string) error {
	want, err := listSyncable(src)
	if err != nil {
		return err
	}
	have, err := listSyncable(dst)
	if err != nil {
		return err
	}
	var diffs []string
	for name, b := range want {
		got, ok := have[name]
		switch {
		case !ok:
			diffs = append(diffs, name+" (missing from copy)")
		case !bytes.Equal(b, got):
			diffs = append(diffs, name+" (differs)")
		}
	}
	for name := range have {
		if _, ok := want[name]; !ok {
			diffs = append(diffs, name+" (not in "+src+")")
		}
	}
	if len(diffs) == 0 {
		return nil
	}
	sort.Strings(diffs)
	return fmt.Errorf("%s is out of sync with %s: %s; run `moon run heph-cli:sync-fragments`", dst, src, strings.Join(diffs, ", "))
}
