const path = require("path");
const {
  app,
  ipcMain,
  BrowserWindow,
  Menu,
  nativeImage,
  Tray,
} = require("electron");
const logger = require("electron-log");
const { preset } = require("./utils/common");
const { killAgentProcess, startAgent } = require("./agent/agent");
const { checkUpdate } = require("./update");
const {
  init: initRpaDb,
  handleMainProcessListener,
  handleOpenUrlInNewWindowListener,
  isReadyToInstallUpdate,
} = require("./ipc/ipc");
const { dailyTask } = require("./cron/cron");
const Store = require('electron-store');
const store = new Store()

// 预设参数
const {
  isMac,
  isWindows,
  launchFromUrlScheme,
  isTest,
  PRODUCT_NAME,
  urlScheme,
  APP_URL,
} = preset();

// 尝试获取单实例锁
const singleInstanceLock = app.requestSingleInstanceLock();
if (!singleInstanceLock) {
  // 如果获取锁失败，说明已经有另一个实例在运行，此时可以直接退出应用
  app.exit();
}
const preload = path.join(__dirname, "./preload.js");
/** @type BrowserWindow */
let win = null;
let splashWin = null;
let tray = null;

// 系统托盘图标
const trayPath = isTest
  ? path.join(
    app.getAppPath(),
    isWindows ? "./public/icon.ico" : "./public/22x22.png"
  )
  : path.join(__dirname, "..", "public/22x22.png");
const trayIcon = nativeImage.createFromPath(trayPath);

// 窗口图标
const windowIconPath = isTest
  ? path.join(
    app.getAppPath(),
    isWindows ? "./public/icon.ico" : "./public/512x512.png"
  )
  : path.join(__dirname, "..", "public/icon.ico");
const windowIcon = nativeImage.createFromPath(windowIconPath);

// 是否准备安装更新
// let readyToInstallUpdate = false;
if (launchFromUrlScheme && process.defaultApp) {
  app.setAsDefaultProtocolClient(urlScheme, process.execPath, [
    path.resolve(process.argv[1]),
  ]);
} else {
  app.setAsDefaultProtocolClient(urlScheme);
}

/**
 * 处理URL Scheme方式打开客户端
 */
function handleUrlScheme(url) {
  if (!url || typeof url !== 'string') return false;

  try {
    const schemePrefix = `${urlScheme}://`;
    if (!url.toLowerCase().startsWith(schemePrefix.toLowerCase())) return false;

    const urlWithoutScheme = url.substring(schemePrefix.length);
    if (!urlWithoutScheme.startsWith('auth')) return false;

    // 提取auth后面的所有参数
    const queryPart = urlWithoutScheme.substring(4);
    const apiPath = `/api/agent/agent/auth2${queryPart}`;

    logger.info(`Requesting URL Scheme: ${apiPath}`);

    const http = require('http');
    const agentPort = isTest ? 8838 : 8848; // 暂时写死, 不支持动态配置
    const options = {
      hostname: 'localhost',
      port: agentPort,
      path: apiPath,
      method: 'GET',
    };

    const req = http.request(options);
    req.on('error', error => {
      logger.error('Auth with URL Scheme failed:', error);
    });
    req.end();

    if (!win) return false;
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
    return true;
  } catch (error) {
    logger.error('Failed to handle URL scheme:', error);
    return false;
  }
}

// macos程序坞图标设置
if (isMac) {
  const iconPath = isTest
    ? path.join(app.getAppPath(), "./public", "128x128.png")
    : path.join(app.getAppPath(), "..", "..", "public/128x128.png");
  app.dock.setIcon(nativeImage.createFromPath(iconPath));
  // 点击程序坞激活程序时显示主窗口
  app.on("activate", () => {
    if (!win) return;

    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  });
}

// 解决跨域问题
app.commandLine.appendSwitch("disable-web-security");

/**
 * 监听应用退出事件
 */
app.on("before-quit", () => {
  killAgentProcess();
});

/**
 * 再次唤醒应用时激活主窗口
 */
app.on("second-instance", (event, commandLine) => {
  const urlArg = commandLine.find(arg =>
    arg && typeof arg === 'string' && arg.toLowerCase().startsWith(`${urlScheme}://`)
  );

  if (urlArg && handleUrlScheme(urlArg)) return;

  if (win) {
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  }
});

/**
 * 通过URL Scheme打开程序激活主窗口
 */
app.on("open-url", (event, url) => {
  event.preventDefault();
  if (handleUrlScheme(url)) return;
  if (win) win.focus();
});

/**
 * 创建主窗口
 */
function createWindow() {
  logger.info("current dir", __dirname);

  let title = `${PRODUCT_NAME} | ${app.getVersion()}`;
  let splashTitle = `${PRODUCT_NAME}`;
  // 获取保存的窗口大小和位置
  const windowBounds = store.get('windowBounds') || { width: 1280, height: 800 };

  // 设置窗口属性
  win = new BrowserWindow({
    title: title,
    icon: windowIcon,
    minWidth: 1280,
    minHeight: 800,
    frame: true,
    show: false,
    webPreferences: {
      preload: preload,
      devTools: true,
      nodeIntegration: true,
      webSecurity: false,
    },
    ...windowBounds
  });
  splashWin = new BrowserWindow({
    title: splashTitle,
    icon: windowIcon,
    minWidth: 1280,
    minHeight: 800,
    frame: true,
    transparent: false,
    alwaysOnTop: true,
    ...windowBounds
  });
  //win?.webContents.openDevTools();
  /// 关闭窗口处理 暂时隐藏窗口 后续添加提示框及保存行为 TODO
  win.on("close", (e) => {
    if (!isMac) {
      e.preventDefault();
      win?.hide();
      return;
    }
    if (!isReadyToInstallUpdate()) {
      e.preventDefault();
      win?.hide();
    }
  });

  win.on('resize', () => {
    // 保存窗口大小和位置
    store.set('windowBounds', win.getBounds());
  });

  win.on('move', () => {
    // 保存窗口大小和位置
    store.set('windowBounds', win.getBounds());
  });

  win.webContents.on(
    "did-fail-load",
    (event, errorCode, errorDescription, validatedURL, isMainFrame) => {
      console.log(
        "Page load failed from url:",
        validatedURL,
        "isMainFrame:",
        isMainFrame,
        "error code and msg:",
        errorCode,
        errorDescription
      );
      if (isMainFrame) {
        let errorPath = isTest
          ? path.join(app.getAppPath(), "./public/error-load/index.html")
          : path.join(__dirname, "..", "public/error-load/index.html");
        win?.loadFile(errorPath)?.then(() => {
          logger.info(app.getName() + " started");
        });
      }
    }
  );
  // 重写window title
  win.webContents.on("did-finish-load", () => {
    win?.setTitle(title);
  });

  win.webContents.on("page-title-updated", (event, winTitle) => {
    if (winTitle !== title || win?.getTitle() !== title) {
      win?.setTitle(title);
    }
  });

  win.webContents.on("context-menu", (e, param) => {
    const { isEditable, selectionText } = param;
    if (isEditable) {
      Menu.buildFromTemplate([
        { role: "undo", label: "Undo", enabled: param.editFlags.canUndo },
        {
          role: "selectAll",
          label: "Select All",
          enabled: param.editFlags.canSelectAll,
        },
        // 分割线
        { type: "separator" },
        // enabled 设置选项是否可用
        { role: "cut", label: "Cut", enabled: param.editFlags.canCut },
        { role: "copy", label: "Copy", enabled: param.editFlags.canCopy },
        { role: "paste", label: "Paste", enabled: param.editFlags.canPaste },
      ]).popup();
      return;
    }

    if (selectionText && selectionText.trim() !== "") {
      Menu.buildFromTemplate([
        { role: "copy", label: "Copy", enabled: param.editFlags.canCopy },
      ]).popup();
      return;
    }
  });

  splashWin.webContents.on("did-finish-load", () => {
    splashWin?.setTitle(splashTitle);
  });
  /// 设置窗口页面
  if (process.env.NODE_ENV === "development" && !launchFromUrlScheme) {
    // dev模式下测试自动更新需要模拟为已打包
    Object.defineProperty(app, "isPackaged", {
      get() {
        return true;
      },
    });
    // 加载splash页面
    const splashPath = path.join(app.getAppPath(), "./public/splash/index.html");
    splashWin.loadFile(splashPath).then(() => {
      logger.info("dev splash page loaded");
    });
    reloadWinPage("dev");
  } else {
    // 加载splash页面
    const splashPath = path.join(__dirname, "..", "public/splash/index.html");
    splashWin.loadFile(splashPath).then(() => {
      logger.info("splash page loaded");
    });
    // 加载线上页面
    reloadWinPage("prod");
  }
  // 加载完毕之后覆盖splash页面
  win.once("ready-to-show", () => {
    splashWin?.destroy();
    win?.show();
    win?.focus();
    if (pendingUrlScheme && handleUrlScheme(pendingUrlScheme)) {
      pendingUrlScheme = null;
    }
  });
  // 注册windows快捷键 mac默认自带窗口快捷键
  if (isWindows) {
    // 关闭菜单显示
    win.setMenuBarVisibility(false);
  }
}

function reloadWinPage(mode = "dev") {
  const reloadURL = mode === "dev" ? "http://localhost:3030" : APP_URL;
  win?.loadURL(reloadURL).then(() => {
    logger.info(
      app.getName() + `mode [${mode}]` + " started by load dev server"
    );
  });
}

/**
 * 创建系统托盘
 */
function createTray() {
  tray = new Tray(trayIcon);
  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Open UI",
      click: function () {
        import("open").then((module) => {
          module.default(APP_URL).then(() => {
            logger.info("Opened UI " + APP_URL);
          });
        });
      },
    },
    {
      label: "Show",
      click: function () {
        try {
          win?.show();
        } catch (error) {
          logger.info("show window event emmit error: ", error)
        }
      },
    },
    {
      label: "Hide",
      click: function () {
        try {
          win?.hide();
        } catch (error) {
          logger.info("hide window event emmit error: ", error)
        }
      },
    },
    {
      label: "Restart",
      click: function () {
        killAgentProcess();
        app.relaunch();
        app.exit();
      },
    },
    {
      label: "Quit",
      click: function () {
        killAgentProcess();
        app.exit();
      },
    },
  ]);
  tray.setToolTip(PRODUCT_NAME);
  tray.on("click", () => {
    try {
      win?.show();
    } catch (error) {
      logger.info("show window event emmit error: ", error)
    }
  });
  // macos不能直接setContextMenu否则单击会显示托盘菜单 TODO Linux系统托盘行为适配
  if (isMac) {
    tray.on("right-click", () => {
      contextMenu.popup();
    });
  } else {
    tray.setContextMenu(contextMenu);
  }
}

function startApp() {
  // 创建主窗口
  createWindow();
  // 创建系统托盘
  createTray();
  // 检查更新
  checkUpdate(win, ipcMain);
}

startAgent();

let pendingUrlScheme = null;

if (isWindows && process.argv.length > 1) {
  const urlArg = process.argv.find(arg =>
    arg && typeof arg === 'string' && arg.toLowerCase().startsWith(`${urlScheme}://`)
  );
  if (urlArg) pendingUrlScheme = urlArg;
}

app.whenReady().then(() => {
  startApp();
  handleMainProcessListener(win);
  handleOpenUrlInNewWindowListener(windowIcon)
  initRpaDb();
}).catch(reason => {
  logger.error(reason)
})
