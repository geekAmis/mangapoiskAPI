package ru.mangapoisk.reborn.ui.navigation

import android.net.Uri
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bookmarks
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.ui.auth.AuthScreen
import ru.mangapoisk.reborn.ui.catalog.CatalogScreen
import ru.mangapoisk.reborn.ui.detail.DetailScreen
import ru.mangapoisk.reborn.ui.home.HomeScreen
import ru.mangapoisk.reborn.ui.library.LibraryScreen
import ru.mangapoisk.reborn.ui.reader.ReaderScreen
import ru.mangapoisk.reborn.ui.settings.SettingsScreen
import ru.mangapoisk.reborn.ui.sources.SourcesScreen

private object Routes {
    const val HOME = "home"
    const val CATALOG = "catalog?source={source}&sort={sort}"
    const val LIBRARY = "library"
    const val SETTINGS = "settings"
    const val SOURCES = "sources"
    const val DETAIL = "manga/{mangaId}"
    const val READER =
        "reader/{chapterId}?mangaId={mangaId}&title={title}&cover={cover}&startPage={startPage}"
    const val AUTH = "auth?mode={mode}"
}

private data class TopLevelDestination(
    val route: String,
    val labelRes: Int,
    val icon: ImageVector,
)

private val topLevelDestinations = listOf(
    TopLevelDestination(Routes.HOME, R.string.nav_home, Icons.Default.Home),
    TopLevelDestination("catalog", R.string.nav_catalog, Icons.Default.Search),
    TopLevelDestination(Routes.LIBRARY, R.string.nav_library, Icons.Default.Bookmarks),
    TopLevelDestination(Routes.SETTINGS, R.string.nav_profile, Icons.Default.Person),
)

@Composable
fun AppRoot() {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val baseRoute = currentRoute?.substringBefore('?') ?: Routes.HOME
    val showNavigation = baseRoute == "home" ||
        baseRoute == "catalog" ||
        baseRoute == Routes.LIBRARY ||
        baseRoute == Routes.SETTINGS

    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val wide = maxWidth >= 720.dp

        // Keep the NavHost in a stable slot: hiding the navigation chrome must
        // not recreate the graph or lose destination scroll state.
        if (wide) {
            Row(modifier = Modifier.fillMaxSize()) {
                if (showNavigation) {
                    AppNavigationRail(
                        currentRoute = baseRoute,
                        onNavigate = { route -> navigateTopLevel(navController, route) },
                    )
                }
                AppNavHost(
                    navController = navController,
                    modifier = Modifier
                        .fillMaxSize()
                        .weight(1f),
                )
            }
        } else {
            Scaffold(
                bottomBar = {
                    if (showNavigation) {
                        AppNavigationBar(
                            currentRoute = baseRoute,
                            onNavigate = { route -> navigateTopLevel(navController, route) },
                        )
                    }
                },
                contentWindowInsets = WindowInsets(0, 0, 0, 0),
                containerColor = MaterialTheme.colorScheme.background,
            ) { padding ->
                AppNavHost(
                    navController = navController,
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding),
                )
            }
        }
    }
}

@Composable
private fun AppNavigationBar(
    currentRoute: String?,
    onNavigate: (String) -> Unit,
) {
    NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
        topLevelDestinations.forEach { destination ->
            NavigationBarItem(
                selected = currentRoute == destination.route,
                onClick = { onNavigate(destination.route) },
                icon = {
                    Icon(
                        imageVector = destination.icon,
                        contentDescription = null,
                    )
                },
                label = { Text(stringResource(destination.labelRes)) },
            )
        }
    }
}

@Composable
private fun AppNavigationRail(
    currentRoute: String?,
    onNavigate: (String) -> Unit,
) {
    NavigationRail(containerColor = MaterialTheme.colorScheme.surface) {
        topLevelDestinations.forEach { destination ->
            NavigationRailItem(
                selected = currentRoute == destination.route,
                onClick = { onNavigate(destination.route) },
                icon = {
                    Icon(
                        imageVector = destination.icon,
                        contentDescription = null,
                    )
                },
                label = { Text(stringResource(destination.labelRes)) },
                alwaysShowLabel = true,
            )
        }
    }
}

@Composable
private fun AppNavHost(
    navController: NavHostController,
    modifier: Modifier = Modifier,
) {
    NavHost(
        navController = navController,
        startDestination = Routes.HOME,
        modifier = modifier,
    ) {
        composable(Routes.HOME) {
            HomeScreen(
                onMangaClick = { mangaId ->
                    navController.navigate("manga/${Uri.encode(mangaId)}")
                },
                onContinueReading = { progress ->
                    navController.navigate(
                        readerRoute(
                            chapterId = progress.chapterId,
                            startPage = progress.page.coerceAtLeast(1),
                            mangaId = progress.mangaId,
                            title = progress.mangaTitle,
                            cover = progress.posterUrl,
                        ),
                    )
                },
                onOpenReader = { chapterId, startPage, mangaId, title, cover ->
                    navController.navigate(
                        readerRoute(
                            chapterId = chapterId,
                            startPage = startPage,
                            mangaId = mangaId,
                            title = title,
                            cover = cover,
                        ),
                    )
                },
                onSourceClick = { source ->
                    navController.navigate("catalog?source=${Uri.encode(source)}") {
                        popUpTo(navController.graph.findStartDestination().id) {
                            saveState = true
                        }
                        launchSingleTop = true
                    }
                },
                onAllSources = { navController.navigate(Routes.SOURCES) },
                onCatalogSort = { sort ->
                    navController.navigate("catalog?sort=${Uri.encode(sort)}") {
                        popUpTo(navController.graph.findStartDestination().id) {
                            saveState = true
                        }
                        launchSingleTop = true
                    }
                },
            )
        }

        composable(
            route = Routes.CATALOG,
            arguments = listOf(
                navArgument("source") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
                navArgument("sort") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) {
            CatalogScreen(
                onMangaClick = { mangaId ->
                    navController.navigate("manga/${Uri.encode(mangaId)}")
                },
            )
        }

        composable(Routes.LIBRARY) {
            LibraryScreen(
                onMangaClick = { mangaId ->
                    navController.navigate("manga/${Uri.encode(mangaId)}")
                },
                onOpenReader = { chapterId, startPage, mangaId, title, cover ->
                    navController.navigate(
                        readerRoute(chapterId, startPage, mangaId, title, cover),
                    )
                },
                onBrowseCatalog = {
                    navigateTopLevel(navController, "catalog")
                },
            )
        }

        composable(Routes.SETTINGS) {
            SettingsScreen(
                onOpenAuth = { register ->
                    navController.navigate(
                        if (register) "auth?mode=register" else "auth?mode=login",
                    )
                },
                onOpenSources = { navController.navigate(Routes.SOURCES) },
            )
        }

        composable(Routes.SOURCES) {
            SourcesScreen(onBack = { navController.popBackStack() })
        }

        composable(
            route = Routes.DETAIL,
            arguments = listOf(
                navArgument("mangaId") { type = NavType.StringType },
            ),
        ) { entry ->
            DetailScreen(
                onBack = { navController.popBackStack() },
                onReadChapter = { chapterId, startPage, title, cover ->
                    navController.navigate(
                        readerRoute(
                            chapterId = chapterId,
                            startPage = startPage,
                            mangaId = entry.arguments?.getString("mangaId").orEmpty(),
                            title = title,
                            cover = cover,
                        ),
                    )
                },
            )
        }

        composable(
            route = Routes.READER,
            arguments = listOf(
                navArgument("chapterId") { type = NavType.StringType },
                navArgument("mangaId") {
                    type = NavType.StringType
                    defaultValue = ""
                },
                navArgument("title") {
                    type = NavType.StringType
                    defaultValue = ""
                },
                navArgument("cover") {
                    type = NavType.StringType
                    defaultValue = ""
                },
                navArgument("startPage") {
                    type = NavType.IntType
                    defaultValue = 1
                },
            ),
        ) {
            ReaderScreen(onBack = { navController.popBackStack() })
        }

        composable(
            route = Routes.AUTH,
            arguments = listOf(
                navArgument("mode") {
                    type = NavType.StringType
                    defaultValue = "login"
                },
            ),
        ) { entry ->
            AuthScreen(
                initialRegister = entry.arguments?.getString("mode") == "register",
                onBack = { navController.popBackStack() },
                onAuthenticated = { navController.popBackStack() },
            )
        }
    }
}

private fun navigateTopLevel(navController: NavHostController, route: String) {
    navController.navigate(route) {
        popUpTo(navController.graph.findStartDestination().id) {
            saveState = true
        }
        launchSingleTop = true
        restoreState = true
    }
}

private fun readerRoute(
    chapterId: String,
    startPage: Int,
    mangaId: String,
    title: String,
    cover: String?,
): String {
    return "reader/${Uri.encode(chapterId)}" +
        "?mangaId=${Uri.encode(mangaId)}" +
        "&title=${Uri.encode(title)}" +
        "&cover=${Uri.encode(cover.orEmpty())}" +
        "&startPage=${startPage.coerceAtLeast(1)}"
}
