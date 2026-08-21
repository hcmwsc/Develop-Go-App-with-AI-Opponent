// Weiqi AI desktop launcher.
//
// Responsibilities:
//   1. Detect / auto-install Python if needed (Windows winget / python.org installer).
//   2. Create a virtual env on first run and install requirements.txt.
//   3. Start uvicorn serving the FastAPI backend + embeded frontend.
//   4. Open the default browser to http://127.0.0.1:8000/.
//   5. Keep running until the user presses Ctrl-C or closes the window.
//
// Cross-compile:
//   CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -o WeiqiAI.exe .
package main

import (
	"context"
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
)

//go:embed all:frontend_dist
var frontendFS embed.FS

//go:embed all:backend_src
var backendFS embed.FS

// sentinel marker used so we can check whether extraction has already happened.
// This file MUST exist inside backend_src/.
const backendSentinel = "placeholder.txt"

const (
	httpAddr    = "127.0.0.1:8000"
	httpURL     = "http://" + httpAddr + "/"
	httpTimeout = 20 * time.Second
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "[weiqi] 错误:", err)
		if runtime.GOOS == "windows" {
			// Keep console visible so the user can read the error.
			fmt.Println("")
			fmt.Println("按回车键退出...")
			fmt.Scanln()
		}
		os.Exit(1)
	}
}

func run() error {
	// Determine a persistent working directory next to the exe.
	workDir, err := workDirectory()
	if err != nil {
		return err
	}
	fmt.Println("[weiqi] 工作目录:", workDir)

	// Extract backend source files into workDir/backend on first run.
	backendDir := filepath.Join(workDir, "backend")
	if err := extractIfNeeded(backendFS, "backend_src", backendDir); err != nil {
		return fmt.Errorf("解包后端失败: %w", err)
	}

	// Ensure Python env is ready (idempotent).
	pythonBin, err := ensurePython(workDir, backendDir)
	if err != nil {
		return err
	}

	// Start uvicorn in the background.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	cmd := exec.CommandContext(ctx, pythonBin, "-m", "uvicorn", "app.main:app",
		"--host", "127.0.0.1", "--port", "8000")
	cmd.Dir = backendDir
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = append(os.Environ(), "WEIQI_STATIC_DIR="+extractFrontend(workDir))

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("启动后端失败: %w", err)
	}

	// Wait for backend to become reachable.
	if err := waitForBackend(httpTimeout); err != nil {
		return err
	}

	// Open the browser.
	if err := openBrowser(httpURL); err != nil {
		fmt.Fprintln(os.Stderr, "[weiqi] 自动打开浏览器失败，请手动访问:", httpURL)
	} else {
		fmt.Println("[weiqi] 浏览器已打开:", httpURL)
	}

	fmt.Println("[weiqi] 围棋 AI 正在运行。关闭此窗口或按 Ctrl-C 退出。")

	// Wait for interrupt.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	<-sigCh
	fmt.Println("\n[weiqi] 正在关闭...")
	cancel()
	shutdownCmd(cmd)
	return nil
}

func shutdownCmd(cmd *exec.Cmd) {
	done := make(chan struct{})
	go func() { _ = cmd.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		_ = cmd.Process.Kill()
		<-done
	}
}

// workDirectory returns a writable directory next to the executable
// (or the current working directory as a fallback).
func workDirectory() (string, error) {
	exe, err := os.Executable()
	dir := filepath.Dir(exe)
	if err != nil || dir == "." || dir == "" {
		dir, err = os.Getwd()
	}
	if err != nil {
		return "", err
	}
	marker := filepath.Join(dir, ".weiqi_home_marker")
	if err := os.WriteFile(marker, []byte{}, 0o644); err != nil {
		// Fallback to home/.weiqi if the dir is read-only (e.g. Program Files).
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		dir = filepath.Join(home, ".weiqi-ai")
		return dir, os.MkdirAll(dir, 0o755)
	}
	_ = os.Remove(marker)
	return dir, nil
}

// extractIfNeeded copies files from an embedded FS tree into destDir.
// The first file (by walk order) is used as the sentinel to decide whether
// extraction has already been performed, so any previously extracted copy
// is reused unchanged.
func extractIfNeeded(fsys embed.FS, prefix, destDir string) error {
	alreadyPresent := false
	err := fs.WalkDir(fsys, prefix, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel := strings.TrimPrefix(path, prefix)
		if rel == "" {
			return nil
		}
		target := filepath.Join(destDir, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		if _, sErr := os.Stat(target); sErr == nil {
			alreadyPresent = true
			return nil
		}
		data, rErr := fsys.ReadFile(path)
		if rErr != nil {
			return rErr
		}
		return os.WriteFile(target, data, 0o644)
	})
	if err != nil {
		return err
	}
	if alreadyPresent {
		return nil
	}
	return nil
}

// extractFrontend extracts the frontend assets next to backend and returns
// the directory to pass to WEIQI_STATIC_DIR.
func extractFrontend(workDir string) string {
	dest := filepath.Join(workDir, "frontend")
	_ = extractIfNeeded(frontendFS, "frontend_dist", dest)
	return dest
}

// ensurePython guarantees a working Python interpreter with the backend's
// dependencies installed. Returns the python executable path.
func ensurePython(workDir, backendDir string) (string, error) {
	// 1. Find any python3/python on PATH.
	candidates := []string{"python", "python3", "python3.exe"}
	py := ""
	for _, c := range candidates {
		if p, err := exec.LookPath(c); err == nil {
			if err := probePython(p); err == nil {
				py = p
				break
			}
		}
	}

	if py == "" {
		return autoInstallPython()
	}

	// 2. Ensure dependencies are installed.
	venvDir := filepath.Join(workDir, ".venv")
	venvPython := filepath.Join(venvDir, "Scripts", "python.exe")
	if runtime.GOOS != "windows" {
		venvPython = filepath.Join(venvDir, "bin", "python")
	}

	if _, err := os.Stat(venvPython); err == nil {
		if err := probeUvicorn(venvPython); err == nil {
			return venvPython, nil
		}
		// Venv is present but broken / missing deps — remove & re-create.
		fmt.Println("[weiqi] 虚拟环境损坏，将重新创建...")
		_ = os.RemoveAll(venvDir)
	}

	fmt.Println("[weiqi] 创建 Python 虚拟环境...")
	if err := runCmd(workDir, py, "-m", "venv", venvDir); err != nil {
		return "", fmt.Errorf("创建虚拟环境失败: %w", err)
	}

	reqFile := filepath.Join(backendDir, "requirements.txt")
	if _, err := os.Stat(reqFile); err == nil {
		fmt.Println("[weiqi] 安装依赖包（首次运行，可能需要几分钟）...")
		if err := runCmd(workDir, venvPython, "-m", "pip", "install", "--disable-pip-version-check", "-r", reqFile); err != nil {
			return "", fmt.Errorf("pip install 失败: %w", err)
		}
	}
	return venvPython, nil
}

func probePython(p string) error {
	out, err := exec.Command(p, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)").CombinedOutput()
	if err != nil {
		return fmt.Errorf("python 版本不满足 (>= 3.10): %s: %s", p, out)
	}
	return nil
}

// probeUvicorn returns nil if the given python has uvicorn importable
// (i.e. the backend's requirements have been installed into that env).
func probeUvicorn(p string) error {
	return exec.Command(p, "-c", "import uvicorn, fastapi; import sys; sys.exit(0)").Run()
}

func runCmd(dir, name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.Dir = dir
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

// autoInstallPython attempts to install Python on Windows via winget,
// or shows the user where to download the installer if not.
func autoInstallPython() (string, error) {
	if runtime.GOOS != "windows" {
		return "", errors.New("未检测到 Python，请先安装 Python 3.10+ 或把 python 加入 PATH")
	}
	fmt.Println("[weiqi] 未检测到 Python，尝试使用 winget 自动安装...")
	cmd := exec.Command("winget", "install", "-e", "--id", "Python.Python.3.12", "--accept-package-agreements", "--accept-source-agreements")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		fmt.Println("winget 未安装或失败，请手动安装 Python 3.12:")
		fmt.Println("  官网下载: https://www.python.org/downloads/")
		fmt.Println("  或使用: 微软商店 搜索 Python 3.12")
		return "", errors.New("未找到 Python，请先安装后再重新启动本程序")
	}
	fmt.Println("[weiqi] winget 已触发安装，请按提示完成安装，然后重新运行本程序。")
	os.Exit(0)
	return "", nil
}

// waitForBackend polls http://127.0.0.1:8000/health until it returns 200.
func waitForBackend(timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		c, err := net.DialTimeout("tcp", httpAddr, 1*time.Second)
		if err == nil {
			_ = c.Close()
			req, err := http.NewRequest("GET", "http://"+httpAddr+"/health", nil)
			if err == nil {
				resp, err := http.DefaultClient.Do(req)
				if err == nil {
					resp.Body.Close()
					if resp.StatusCode == 200 {
						return nil
					}
				}
			}
		}
		time.Sleep(400 * time.Millisecond)
	}
	return errors.New("后端启动超时，请查看控制台输出排查问题")
}

// openBrowser opens the given URL in the default system browser.
func openBrowser(url string) error {
	switch runtime.GOOS {
	case "windows":
		return exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
	case "darwin":
		return exec.Command("open", url).Start()
	default:
		return exec.Command("xdg-open", url).Start()
	}
}
