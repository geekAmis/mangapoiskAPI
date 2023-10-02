function hot_load_more(name,glva,tom){

	await fetch(`${window.location.hostname}:490/api/new_page?name=${name}glva=${glva}&tom=${tom}`)
				  .then(response => response.json())
				  .then(data => {
				    console.log(data["props"]["chapter"]["data"]["pages"]);
				  });
}